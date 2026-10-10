"""Synchronous operations run by the GUI's worker thread."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .batch_io import read_queries, write_report
from .config import Config
from .service import PaperGetService
from .store import Store


@dataclass(frozen=True)
class Task:
    kind: str
    query: str = ""
    path: Path | None = None
    column: str = "doi_or_title"
    format: str = "json"


def perform(task: Task, config: Config):
    """Run one task with resources created and closed in the calling thread."""
    if task.kind in {"search", "inspect", "download"}:
        with PaperGetService(config) as service:
            if task.kind == "search":
                return service.search_title(task.query)
            return service.fetch(task.query, inspect=task.kind == "inspect")
    if task.kind == "import":
        if task.path is None:
            raise ValueError("No input file selected")
        return read_queries(task.path, task.column)
    if task.kind in {"history", "export"}:
        database = config.output_dir / "paperget.sqlite3"
        if not database.is_file():
            rows = []
        else:
            with Store(database) as store:
                rows = store.export_json()
        if task.kind == "history":
            return sorted(rows, key=lambda row: row["updated_at"], reverse=True)
        if task.path is None:
            raise ValueError("No export file selected")
        write_report(task.path, rows, task.format)
        return task.path
    raise ValueError(f"Unknown task: {task.kind}")
