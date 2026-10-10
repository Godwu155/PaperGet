from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote


Status = Literal["downloaded", "existing", "found", "not_found", "ambiguous", "failed"]


@dataclass(frozen=True)
class Paper:
    doi: str
    title: str = ""
    year: int | None = None
    authors: tuple[str, ...] = ()


@dataclass(frozen=True)
class TitleMatch:
    doi: str
    title: str
    year: int | None
    authors: tuple[str, ...]
    match_score: float
    source: str = "crossref"

    def to_dict(self) -> dict:
        return {**asdict(self), "authors": list(self.authors), "doi_url": f"https://doi.org/{quote(self.doi, safe='/')}"}


@dataclass
class SearchResult:
    query: str
    status: Literal["found", "not_found", "failed"]
    candidates: list[TitleMatch] = field(default_factory=list)
    error_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "status": self.status,
            "count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    version: str | None = None
    license: str | None = None
    landing_page_url: str | None = None


@dataclass
class Result:
    query: str
    status: Status
    doi: str | None = None
    title: str | None = None
    path: Path | None = None
    source: str | None = None
    version: str | None = None
    sha256: str | None = None
    error_code: str | None = None
    message: str | None = None
    candidates: list[Candidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["path"] = str(self.path) if self.path else None
        return data
