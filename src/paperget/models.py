from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


Status = Literal["downloaded", "existing", "found", "not_found", "ambiguous", "failed"]


@dataclass(frozen=True)
class Paper:
    doi: str
    title: str = ""
    year: int | None = None
    authors: tuple[str, ...] = ()


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
