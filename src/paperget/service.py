from __future__ import annotations

import sqlite3
from urllib.parse import urlparse

from .config import Config
from .downloader import Downloader, filename_for_doi, pdf_is_valid
from .errors import PaperGetError
from .http import HttpClient
from .models import Candidate, Result, SearchResult
from .providers.openalex import OpenAlexProvider
from .providers.scihub import SciHubProvider
from .resolver import Resolver
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
        if not query:
            return self._save(Result(query=query, status="failed", error_code="invalid_input", message="Empty query"), inspect)
        try:
            paper = self.resolver.resolve(query, choose=choose)
        except PaperGetError as exc:
            status = "ambiguous" if exc.code == "ambiguous_title" else "not_found" if exc.code == "not_found" else "failed"
            return self._save(Result(query=query, status=status, error_code=exc.code, message=str(exc)), inspect)

        destination = self.config.output_dir / filename_for_doi(paper.doi)
        if not inspect and not self.config.force and pdf_is_valid(destination):
            file_info = self.store.file_info(paper.doi)
            return self._save(Result(
                query=query, status="existing", doi=paper.doi, title=paper.title,
                path=destination, sha256=self.downloader._hash(destination),
                source=file_info[0] if file_info else None,
                version=file_info[1] if file_info else None,
            ), inspect)

        candidates: list[Candidate] = []
        errors: list[str] = []
        error_codes: list[str] = []
        blocked_hosts: set[str] = set()
        for name in self.config.source_order:
            provider = self.providers.get(name)
            if provider is None:
                continue
            try:
                found = provider.find(paper)
            except PaperGetError as exc:
                errors.append(f"{name}: {exc.code}: {exc}")
                error_codes.append(exc.code)
                continue
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"{name}: invalid_response: {exc}")
                continue
            if self.config.prefer_published:
                found.sort(key=lambda c: c.version != "publishedVersion")
            candidates.extend(found)
            try:
                self.store.record_candidates(query, found)
            except sqlite3.Error:
                pass
            if not inspect:
                for candidate in found:
                    host = (urlparse(candidate.url).hostname or "").lower()
                    if host in blocked_hosts:
                        continue
                    try:
                        sha256 = self.downloader.download(candidate.url, destination, force=self.config.force)
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
                message="; ".join(errors) or (self._no_pdf_message() if not candidates else None),
            )
        status = "failed" if errors else "not_found"
        error_code = next((code for code in error_codes if code in {"forbidden", "rate_limited", "timeout", "connection_error", "invalid_pdf", "disk_error"}), None)
        result = Result(
            query=query, status=status, doi=paper.doi, title=paper.title,
            error_code=error_code or ("no_pdf" if not candidates else "download_failed"),
            message="; ".join(errors) or self._no_pdf_message(),
        )
        return self._save(result, inspect)

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
