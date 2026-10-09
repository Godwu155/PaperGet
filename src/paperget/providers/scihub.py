from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

from ..errors import PaperGetError
from ..http import HttpClient
from ..models import Candidate, Paper


class _PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"iframe", "embed"}:
            value = attributes.get("src")
        elif tag == "object":
            value = attributes.get("data")
        elif tag == "a":
            value = attributes.get("href")
            if value and ".pdf" not in value.lower() and "download" not in attributes.get("id", "").lower():
                value = None
        else:
            value = None
        if value:
            self.links.append(value)


class SciHubProvider:
    """Optional HTML adapter. A particular mirror must be tested before use."""

    name = "scihub"

    def __init__(self, http: HttpClient, base_url: str):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PaperGetError("invalid_url", "Sci-Hub base URL must be HTTPS")
        self.http = http
        self.base_url = base_url.rstrip("/") + "/"

    def find(self, paper: Paper) -> list[Candidate]:
        url = urljoin(self.base_url, quote(paper.doi, safe="/"))
        response = self.http.get(url)
        try:
            if response.status_code == 404:
                return []
            if "application/pdf" in response.headers.get("Content-Type", "").lower():
                return [Candidate(url=response.url, source=self.name)]
            if "html" not in response.headers.get("Content-Type", "").lower():
                return []
            parser = _PdfLinks()
            parser.feed(response.text)
            page_url = response.url
        finally:
            response.close()
        links: list[Candidate] = []
        seen: set[str] = set()
        for raw in parser.links:
            candidate_url = urljoin(page_url, raw)
            parsed = urlparse(candidate_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or candidate_url in seen:
                continue
            seen.add(candidate_url)
            links.append(Candidate(url=candidate_url, source=self.name, landing_page_url=page_url))
        return links
