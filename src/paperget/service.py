from __future__ import annotations

import sqlite3
import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from .config import Config
from .downloader import Downloader, filename_for_doi, filename_for_paper, pdf_is_valid
from .errors import PaperGetError
from .http import HttpClient
from .models import Candidate, Paper, Result, SearchResult
from .providers.openalex import OpenAlexProvider
from .providers.scihub import SciHubProvider
from .resolver import Resolver, normalize_doi
from .store import Store


class PaperGetService:
    def __init__(self, config: Config, *, http: HttpClient | None = None, store: Store | None = None):
        self.config = config
        self.http = http or HttpClient()
        self.store = store or Store(config.output_dir / "paperget.sqlite3")
        self.resolver = Resolver(self.http, config.crossref_mailto, self.store)
        self.downloader = Downloader(self.http, config.max_pdf_mb)
        self.providers = {"openalex": OpenAlexProvider(self.http, config.openalex_api_key, self.store)}
        if config.scihub_base_url:
            self.providers["scihub"] = SciHubProvider(self.http, config.scihub_base_url)

    def search_title(self, query: str, *, limit: int = 10) -> SearchResult:
        try:
            matches = self.resolver.search_title(query, limit=limit)
        except PaperGetError as exc:
            return SearchResult(query=query, status="failed", error_code=exc.code, message=str(exc))
        return SearchResult(
            query=query, status="found" if matches else "not_found", candidates=matches,
            message=None if matches else "No title candidates found",
        )

    def fetch(self, query: str, *, inspect: bool = False, choose=None) -> Result:
        query = query.strip()
        run_id = uuid4().hex
        if not query:
            return self._save(Result(query=query, status="failed", error_code="invalid_input", message="Empty query"), inspect)
        try:
            paper = self.resolver.resolve(query, choose=choose)
        except PaperGetError as exc:
            status = "ambiguous" if exc.code == "ambiguous_title" else "not_found" if exc.code == "not_found" else "failed"
            return self._save(Result(query=query, status=status, error_code=exc.code, message=str(exc)), inspect)

        def existing_file():
            if inspect or self.config.force:
                return None
            file_record = self.store.file_record(paper.doi)
            old_destination = self.config.output_dir / filename_for_doi(paper.doi)
            paths = [self.config.output_dir / filename_for_paper(paper.title, paper.doi), old_destination]
            if file_record and file_record[0].resolve().parent == self.config.output_dir.resolve():
                paths.insert(0, file_record[0])
            for existing_path in dict.fromkeys(paths):
                if pdf_is_valid(existing_path):
                    file_info = self.store.file_info(paper.doi)
                    return Result(
                        query=query, status="existing", doi=paper.doi, title=paper.title,
                        path=existing_path, sha256=self.downloader._hash(existing_path),
                        source=file_info[0] if file_info else None,
                        version=file_info[1] if file_info else None,
                    )
            return None

        existing = existing_file()
        if existing:
            return self._save(existing, inspect)
        destination = self.config.output_dir / filename_for_paper(paper.title, paper.doi)

        candidates: list[Candidate] = []
        errors: list[str] = []
        source_notes: list[str] = []
        error_codes: list[str] = []
        blocked_hosts: set[str] = set()
        for name in self.config.source_order:
            provider = self.providers.get(name)
            provider_host = ("api.openalex.org" if name == "openalex" else
                             (urlparse(self.config.scihub_base_url or "").hostname or ""))
            if provider is None:
                if name == "scihub":
                    source_notes.append("Sci-Hub fallback is disabled (set SCIHUB_BASE_URL or use --scihub-url)")
                self._event(run_id, query, paper.doi, name, "discovery", "disabled",
                            error_code="source_disabled", message="Source is not configured",
                            host=provider_host)
                continue
            try:
                found = provider.find(paper)
            except PaperGetError as exc:
                errors.append(f"{name}: {exc.code}: {exc}")
                error_codes.append(exc.code)
                self._event(run_id, query, paper.doi, name, "discovery", "failed",
                            error_code=exc.code, message=str(exc), host=provider_host)
                continue
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"{name}: invalid_response: {exc}")
                error_codes.append("invalid_response")
                self._event(run_id, query, paper.doi, name, "discovery", "failed",
                            error_code="invalid_response", message=str(exc), host=provider_host)
                continue
            if name == "openalex" and not paper.title:
                metadata = self.store.cached("openalex", paper.doi)
                title = metadata.get("title") if isinstance(metadata, dict) else None
                if isinstance(title, str) and title.strip():
                    paper = replace(paper, title=title.strip())
                    destination = self.config.output_dir / filename_for_paper(paper.title, paper.doi)
                    existing = existing_file()
                    if existing:
                        return self._save(existing, inspect)
            if self.config.prefer_published:
                found.sort(key=lambda c: c.version != "publishedVersion")
            if found:
                self._event(run_id, query, paper.doi, name, "discovery", "found",
                            candidate_count=len(found), host=provider_host)
            else:
                code = getattr(provider, "last_empty_reason", None) or (
                    "no_open_pdf" if name == "openalex" else "no_pdf_link"
                )
                note = {
                    "work_not_found": "OpenAlex has no work for this DOI",
                    "no_open_pdf": "No directly downloadable open PDF in metadata",
                    "page_not_found": "Source page returned HTTP 404",
                    "unsupported_content": "Source returned neither HTML nor PDF",
                    "doi_mismatch": "Source page cites a different DOI",
                    "no_pdf_link": "Page did not provide a recognizable PDF link",
                }.get(code, "No PDF candidate from source")
                source_notes.append(f"{name}: {note}")
                self._event(run_id, query, paper.doi, name, "discovery", "empty",
                            error_code=code, message=note, host=provider_host)
            candidates.extend(found)
            try:
                self.store.record_candidates(query, found)
            except sqlite3.Error:
                pass
            if not inspect:
                for candidate in found:
                    host = (urlparse(candidate.url).hostname or "").lower()
                    if host in blocked_hosts:
                        self._event(run_id, query, paper.doi, name, "download", "skipped",
                                    error_code="blocked_host", host=host,
                                    message="Previous request to this host was blocked")
                        continue
                    try:
                        sha256 = self.downloader.download(candidate.url, destination, force=self.config.force)
                        self._event(run_id, query, paper.doi, name, "download", "downloaded", host=host)
                        try:
                            self.store.attempt(query, candidate, "downloaded")
                        except sqlite3.Error:
                            pass
                        return self._save(Result(
                            query=query, status="downloaded", doi=paper.doi, title=paper.title,
                            path=destination, source=candidate.source, version=candidate.version,
                            sha256=sha256,
                        ), inspect)
                    except PaperGetError as exc:
                        self._event(run_id, query, paper.doi, name, "download", "failed",
                                    error_code=exc.code, message=str(exc), host=host)
                        try:
                            self.store.attempt(query, candidate, "failed", exc)
                        except sqlite3.Error:
                            pass
                        errors.append(f"{candidate.source}: {exc.code}: {exc}")
                        error_codes.append(exc.code)
                        if exc.code in {"forbidden", "rate_limited"}:
                            blocked_hosts.add(host)
        if inspect:
            return Result(
                query=query, status="found" if candidates else "failed" if errors else "not_found",
                doi=paper.doi, title=paper.title, candidates=candidates,
                error_code=error_codes[0] if not candidates and error_codes else None,
                message="; ".join(errors + source_notes) or (self._no_pdf_message() if not candidates else None),
            )
        status = "failed" if errors else "not_found"
        error_code = next((code for code in error_codes if code in {"challenge_required", "forbidden", "rate_limited", "timeout", "connection_error", "invalid_pdf", "disk_error"}), None)
        result = Result(
            query=query, status=status, doi=paper.doi, title=paper.title,
            error_code=error_code or ("no_pdf" if not candidates else "download_failed"),
            message="; ".join(errors + source_notes) or self._no_pdf_message(),
        )
        return self._save(result, inspect)

    def import_pdf(self, query: str, source: Path) -> Result:
        doi = normalize_doi(query)
        if not doi:
            return self._save(Result(query=query, status="failed", error_code="invalid_input",
                                     message="Select a DOI before importing a PDF"), False)
        run_id = uuid4().hex
        title = self.store.paper_title(doi)
        if not title:
            crossref = self.store.cached("crossref-doi", doi)
            titles = crossref.get("title") if isinstance(crossref, dict) else None
            if isinstance(titles, list) and titles and isinstance(titles[0], str):
                title = titles[0]
        if not title:
            metadata = self.store.cached("openalex", doi)
            value = metadata.get("title") if isinstance(metadata, dict) else None
            title = value if isinstance(value, str) else ""
        paper = Paper(doi=doi, title=title.strip())
        destination = self.config.output_dir / filename_for_paper(paper.title, doi)
        file_record = self.store.file_record(doi)
        paths = [destination, self.config.output_dir / filename_for_doi(doi)]
        if file_record and file_record[0].resolve().parent == self.config.output_dir.resolve():
            paths.insert(0, file_record[0])
        for existing_path in dict.fromkeys(paths):
            if pdf_is_valid(existing_path):
                return self._save(Result(query=doi, status="existing", doi=doi, title=paper.title,
                                         path=existing_path, source=file_record[1] if file_record else None,
                                         version=file_record[2] if file_record else None,
                                         sha256=self.downloader._hash(existing_path)), False)
        try:
            sha256 = self.downloader.import_file(source, destination)
        except PaperGetError as exc:
            self._event(run_id, doi, doi, "manual", "import", "failed",
                        error_code=exc.code, message=str(exc))
            return self._save(Result(query=doi, status="failed", doi=doi, title=paper.title,
                                     error_code=exc.code, message=str(exc)), False)
        self._event(run_id, doi, doi, "manual", "import", "downloaded")
        return self._save(Result(query=doi, status="downloaded", doi=doi, title=paper.title,
                                 path=destination, source="manual", sha256=sha256), False)

    def _event(self, run_id: str, query: str, doi: str | None, source: str,
               stage: str, status: str, *, error_code: str | None = None,
               message: str | None = None, candidate_count: int = 0,
               host: str | None = None) -> None:
        # Keep diagnostics useful without storing signed PDF URLs or credentials.
        safe_message = re.sub(r"https?://[^\s)]+", "[URL]", message or "")[:300] or None
        try:
            self.store.record_source_event(run_id, query, doi, source, stage, status,
                                           error_code=error_code, message=safe_message,
                                           candidate_count=candidate_count, host=host)
        except sqlite3.Error:
            pass

    def _no_pdf_message(self) -> str:
        message = "No directly downloadable PDF found in the configured sources"
        if "scihub" in self.config.source_order and "scihub" not in self.providers:
            message += "; Sci-Hub fallback is disabled (set SCIHUB_BASE_URL or use --scihub-url)"
        return message

    def _save(self, result: Result, inspect: bool) -> Result:
        if not inspect:
            try:
                self.store.save(result)
            except sqlite3.Error as exc:
                warning = f"Result database unavailable: {exc}"
                result.message = f"{result.message}; {warning}" if result.message else warning
        return result

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
