from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import quote

from .errors import PaperGetError
from .http import HttpClient
from .models import Paper
from .store import Store


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
    date = (item.get("published") or {}).get("date-parts", [[]])
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
    def __init__(self, http: HttpClient, mailto: str | None = None, cache: Store | None = None):
        self.http = http
        self.mailto = mailto
        self.cache = cache

    def resolve(self, query: str, *, choose=None) -> Paper:
        doi = normalize_doi(query)
        if doi:
            cached = self.cache.cached("crossref-doi", doi) if self.cache else None
            if cached:
                try:
                    return _paper(cached)
                except (KeyError, ValueError, TypeError, IndexError):
                    pass
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
                    item = response.json()["message"]
                    paper = _paper(item)
                    if self.cache:
                        self.cache.cache("crossref-doi", doi, item)
                    return paper
                except (KeyError, ValueError, TypeError, IndexError):
                    return Paper(doi=doi)
            finally:
                response.close()

        cache_key = _plain(query)
        cached = self.cache.cached("crossref-title", cache_key) if self.cache else None
        if cached is None:
            params = {"query.title": query, "rows": 5, "select": "DOI,title,published,author"}
            if self.mailto:
                params["mailto"] = self.mailto
            response = self.http.get("https://api.crossref.org/works", params=params)
            try:
                if response.status_code == 404:
                    raise PaperGetError("not_found", f"Title not found: {query}")
                try:
                    items = response.json().get("message", {}).get("items", [])
                    if not isinstance(items, list):
                        raise ValueError("items must be a list")
                except (ValueError, TypeError, AttributeError) as exc:
                    raise PaperGetError("invalid_response", "Crossref returned invalid title results") from exc
            finally:
                response.close()
            if self.cache:
                self.cache.cache("crossref-title", cache_key, {"items": items})
        else:
            items = cached.get("items", [])
        unique: dict[str, dict] = {}
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("DOI"), str):
                unique.setdefault(item["DOI"].lower(), item)
        def candidate_title(item: dict) -> str:
            titles = item.get("title")
            return titles[0] if isinstance(titles, list) and titles and isinstance(titles[0], str) else ""

        ranked = sorted(
            ((title_score(query, candidate_title(i)), i) for i in unique.values()),
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
