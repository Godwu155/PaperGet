from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse, urlsplit

from ..errors import PaperGetError
from ..http import HttpClient
from ..models import Candidate, Paper
from ..resolver import normalize_doi


class _PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self._hidden: list[bool] = []
        self._citation: list[bool] = []
        self.citation: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "").lower()
        hidden = bool(self._hidden and self._hidden[-1]) or (
            attributes.get("id") == "minu"
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if tag not in {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}:
            self._hidden.append(hidden)
            self._citation.append(attributes.get("id") == "citation" or bool(self._citation and self._citation[-1]))
        if hidden:
            return
        if tag in {"iframe", "embed"}:
            value = attributes.get("src")
        elif tag == "object":
            value = attributes.get("data")
        elif tag == "a":
            value = attributes.get("href")
        else:
            value = None
        if value and (
            urlsplit(value).path.lower().endswith(".pdf")
            or (tag != "a" and (attributes.get("id") == "pdf" or attributes.get("type") == "application/pdf"))
        ):
            self.links.append(value)

    def handle_endtag(self, tag):
        if tag not in {"area", "base", "br", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"} and self._hidden:
            self._hidden.pop()
            self._citation.pop()

    def handle_data(self, data):
        if self._citation and self._citation[-1]:
            self.citation.append(data)


class SciHubProvider:
    """Optional HTML adapter. A particular mirror must be tested before use."""

    name = "scihub"

    def __init__(self, http: HttpClient, base_url: str):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PaperGetError("invalid_url", "Sci-Hub base URL must be HTTPS")
        self.http = http
        self.base_url = base_url.rstrip("/") + "/"
        self.last_empty_reason: str | None = None

    def find(self, paper: Paper) -> list[Candidate]:
        self.last_empty_reason = None
        url = urljoin(self.base_url, quote(paper.doi, safe="/"))
        response = self.http.get(url)
        try:
            if response.status_code == 404:
                self.last_empty_reason = "page_not_found"
                return []
            if "application/pdf" in response.headers.get("Content-Type", "").lower():
                return [Candidate(url=response.url, source=self.name)]
            if "html" not in response.headers.get("Content-Type", "").lower():
                self.last_empty_reason = "unsupported_content"
                return []
            parser = _PdfLinks()
            parser.feed(response.text)
            page_url = response.url
            challenge_hint = bool(re.search(
                r"hcaptcha|recaptcha|turnstile|captcha|verify you are human|checking your browser",
                response.text, re.IGNORECASE,
            ))
        finally:
            response.close()
        links: list[Candidate] = []
        citation_doi = normalize_doi(" ".join(parser.citation))
        if citation_doi and citation_doi != paper.doi.lower():
            self.last_empty_reason = "doi_mismatch"
            return []
        if not parser.links and challenge_hint:
            raise PaperGetError("challenge_required", "Sci-Hub page may require human verification")
        seen: set[str] = set()
        for raw in parser.links:
            candidate_url = urljoin(page_url, raw)
            parsed = urlparse(candidate_url)
            if parsed.scheme != "https" or not parsed.hostname or candidate_url in seen:
                continue
            seen.add(candidate_url)
            links.append(Candidate(url=candidate_url, source=self.name, landing_page_url=page_url))
        if not links:
            self.last_empty_reason = "no_pdf_link"
        return links
