from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import quote

from .errors import PaperGetError
from .http import HttpClient
from .models import Paper


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>]+", re.IGNORECASE)


def normalize_doi(value: str) -> str | None:
    text = value.strip()
    match = DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;)")
    return doi.lower()


def _plain(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def title_score(query: str, candidate: str) -> float:
    a, b = _plain(query), _plain(candidate)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb)
    return 0.7 * sequence + 0.3 * jaccard


def _paper(item: dict) -> Paper:
    date = item.get("published", {}).get("date-parts", [[]])
    year = date[0][0] if date and date[0] else None
    return Paper(
        doi=item["DOI"].lower(),
        title=(item.get("title") or [""])[0],
        year=year,
        authors=tuple(
            " ".join(filter(None, [a.get("given"), a.get("family")]))
            for a in item.get("author", [])
        ),
    )


class Resolver:
    def __init__(self, http: HttpClient, mailto: str | None = None):
        self.http = http
        self.mailto = mailto

    def resolve(self, query: str, *, choose=None) -> Paper:
        doi = normalize_doi(query)
        if doi:
            try:
                response = self.http.get(
                    f"https://api.crossref.org/works/{quote(doi, safe='/')}",
                    params={"mailto": self.mailto} if self.mailto else None,
                )
            except PaperGetError:
                return Paper(doi=doi)
            try:
                if response.status_code == 404:
                    return Paper(doi=doi)
                try:
                    return _paper(response.json()["message"])
                except (KeyError, ValueError, TypeError):
                    return Paper(doi=doi)
            finally:
                response.close()

        params = {"query.title": query, "rows": 5, "select": "DOI,title,published,author"}
        if self.mailto:
            params["mailto"] = self.mailto
        response = self.http.get("https://api.crossref.org/works", params=params)
        try:
            if response.status_code == 404:
                raise PaperGetError("not_found", f"Title not found: {query}")
            items = response.json().get("message", {}).get("items", [])
        finally:
            response.close()
        ranked = sorted(
            ((title_score(query, (i.get("title") or [""])[0]), i) for i in items if i.get("DOI")),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.55:
            raise PaperGetError("not_found", f"No credible DOI match for title: {query}")
        top, second = ranked[0][0], ranked[1][0] if len(ranked) > 1 else 0.0
        if top >= 0.88 and top - second >= 0.08:
            return _paper(ranked[0][1])
        choices = [_paper(item) for _, item in ranked[:3]]
        if choose:
            index = choose(choices)
            if index is not None and 0 <= index < len(choices):
                return choices[index]
        options = "; ".join(f"{p.doi} {p.title}" for p in choices)
        raise PaperGetError("ambiguous_title", f"Choose a title match: {options}")
