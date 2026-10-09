from __future__ import annotations

from urllib.parse import quote

from ..http import HttpClient
from ..models import Candidate, Paper


class OpenAlexProvider:
    name = "openalex"

    def __init__(self, http: HttpClient, api_key: str | None = None):
        self.http = http
        self.api_key = api_key

    def find(self, paper: Paper) -> list[Candidate]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        response = self.http.get(
            f"https://api.openalex.org/works/doi:{quote(paper.doi, safe='/')}",
            params={"select": "doi,title,best_oa_location,locations"},
            headers=headers,
        )
        try:
            if response.status_code == 404:
                return []
            work = response.json()
        finally:
            response.close()
        locations = [work.get("best_oa_location"), *(work.get("locations") or [])]
        seen: set[str] = set()
        candidates: list[Candidate] = []
        for loc in locations:
            if not loc or not loc.get("is_oa") or not loc.get("pdf_url"):
                continue
            url = loc["pdf_url"]
            if url in seen:
                continue
            seen.add(url)
            candidates.append(
                Candidate(
                    url=url,
                    source=self.name,
                    version=loc.get("version"),
                    license=loc.get("license"),
                    landing_page_url=loc.get("landing_page_url"),
                )
            )
        return candidates
