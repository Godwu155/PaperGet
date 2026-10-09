from __future__ import annotations

from .config import Config
from .downloader import Downloader, filename_for_doi, pdf_is_valid
from .errors import PaperGetError
from .http import HttpClient
from .models import Candidate, Result
from .providers.openalex import OpenAlexProvider
from .providers.scihub import SciHubProvider
from .resolver import Resolver
from .store import Store


class PaperGetService:
    def __init__(self, config: Config, *, http: HttpClient | None = None, store: Store | None = None):
        self.config = config
        self.http = http or HttpClient()
        self.resolver = Resolver(self.http, config.crossref_mailto)
        self.downloader = Downloader(self.http, config.max_pdf_mb)
        self.store = store or Store(config.output_dir / "paperget.sqlite3")
        self.providers = {"openalex": OpenAlexProvider(self.http, config.openalex_api_key)}
        if config.scihub_base_url:
            self.providers["scihub"] = SciHubProvider(self.http, config.scihub_base_url)

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
            return self._save(Result(
                query=query, status="existing", doi=paper.doi, title=paper.title,
                path=destination, sha256=self.downloader._hash(destination),
            ), inspect)

        candidates: list[Candidate] = []
        errors: list[str] = []
        for name in self.config.source_order:
            provider = self.providers.get(name)
            if provider is None:
                continue
            try:
                found = provider.find(paper)
            except PaperGetError as exc:
                errors.append(f"{name}: {exc.code}: {exc}")
                continue
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(f"{name}: invalid_response: {exc}")
                continue
            if self.config.prefer_published:
                found.sort(key=lambda c: c.version != "publishedVersion")
            candidates.extend(found)
            if not inspect:
                for candidate in found:
                    try:
                        sha256 = self.downloader.download(candidate.url, destination, force=self.config.force)
                        self.store.attempt(query, candidate, "downloaded")
                        return self._save(Result(
                            query=query, status="downloaded", doi=paper.doi, title=paper.title,
                            path=destination, source=candidate.source, version=candidate.version,
                            sha256=sha256,
                        ), inspect)
                    except PaperGetError as exc:
                        self.store.attempt(query, candidate, "failed", exc)
                        errors.append(f"{candidate.source}: {exc.code}: {exc}")
        if inspect:
            return Result(
                query=query, status="found" if candidates else "not_found",
                doi=paper.doi, title=paper.title, candidates=candidates,
                message="; ".join(errors) or None,
            )
        status = "failed" if errors else "not_found"
        result = Result(
            query=query, status=status, doi=paper.doi, title=paper.title,
            error_code="no_pdf" if not candidates else "download_failed",
            message="; ".join(errors) or "No PDF candidate found",
        )
        return self._save(result, inspect)

    def _save(self, result: Result, inspect: bool) -> Result:
        if not inspect:
            self.store.save(result)
        return result

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
