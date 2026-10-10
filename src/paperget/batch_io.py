"""Input and report formats shared by the CLI and desktop application."""

from __future__ import annotations

import csv
import json
from pathlib import Path


REPORT_FIELDS = (
    "query", "doi", "title", "status", "path", "source", "version",
    "sha256", "error_code", "message",
)


def read_queries(path: Path, column: str = "doi_or_title") -> list[str]:
    if path.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("input file must be .txt or .csv")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or column not in reader.fieldnames:
                raise ValueError(f"CSV column not found: {column}")
            return [value for row in reader if (value := (row.get(column) or "").strip())]
    with path.open("r", encoding="utf-8-sig") as stream:
        return [value for line in stream if (value := line.strip()) and not value.startswith("#")]


def write_report(path: Path, rows: list[dict], format: str) -> None:
    if format not in {"json", "csv"}:
        raise ValueError("report format must be json or csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REPORT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
