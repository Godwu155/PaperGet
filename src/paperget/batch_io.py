"""Input and report formats shared by the CLI and desktop application."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .resolver import normalize_doi


REPORT_FIELDS = (
    "query", "doi", "title", "status", "path", "source", "version",
    "sha256", "error_code", "message",
)
DIAGNOSTIC_FIELDS = (
    "run_id", "query", "doi", "source", "stage", "status", "error_code",
    "message", "candidate_count", "host", "created_at",
)


@dataclass(frozen=True)
class BatchPreviewData:
    queries: list[str]
    invalid_rows: list[tuple[int, str]]


def read_batch_preview(path: Path, column: str = "doi_or_title") -> BatchPreviewData:
    """Read GUI input with line-numbered feedback for rows that cannot be queued."""
    if path.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("input file must be .txt or .csv")
    queries: list[str] = []
    invalid_rows: list[tuple[int, str]] = []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or column not in reader.fieldnames:
                raise ValueError(f"CSV column not found: {column}")
            for row in reader:
                value = (row.get(column) or "").strip()
                reason = _invalid_reason(value)
                if reason:
                    invalid_rows.append((reader.line_num, reason))
                else:
                    queries.append(value)
    else:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                value = line.strip()
                if value.startswith("#"):
                    continue
                reason = _invalid_reason(value)
                if reason:
                    invalid_rows.append((line_number, reason))
                else:
                    queries.append(value)
    return BatchPreviewData(queries, invalid_rows)


def _invalid_reason(value: str) -> str | None:
    if not value or not any(char.isalnum() for char in value):
        return "空值或无标题文字"
    if value.casefold().startswith("10.") and not normalize_doi(value):
        return "DOI 格式不完整"
    if value.casefold().startswith(("http://", "https://")) and not normalize_doi(value):
        return "链接中没有 DOI"
    return None


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


def write_report(path: Path, rows: list[dict], format: str, fields=REPORT_FIELDS) -> None:
    if format not in {"json", "csv"}:
        raise ValueError("report format must be json or csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
