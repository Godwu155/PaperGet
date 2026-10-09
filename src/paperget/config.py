from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    output_dir: Path = Path("downloads")
    crossref_mailto: str | None = None
    openalex_api_key: str | None = None
    scihub_base_url: str | None = None
    source_order: tuple[str, ...] = ("openalex", "scihub")
    prefer_published: bool = False
    force: bool = False
    non_interactive: bool = False
    max_pdf_mb: int = 100

    @classmethod
    def from_env(cls, **overrides):
        values = {
            "crossref_mailto": os.getenv("CROSSREF_MAILTO") or None,
            "openalex_api_key": os.getenv("OPENALEX_API_KEY") or None,
            "scihub_base_url": os.getenv("SCIHUB_BASE_URL") or None,
        }
        values.update(overrides)
        return cls(**values)
