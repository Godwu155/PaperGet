from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Candidate, Result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS results (
                query TEXT PRIMARY KEY, doi TEXT, title TEXT, status TEXT NOT NULL,
                path TEXT, source TEXT, version TEXT, sha256 TEXT,
                error_code TEXT, message TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL,
                source TEXT NOT NULL, url TEXT, status TEXT NOT NULL,
                error_code TEXT, message TEXT, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_results_doi ON results(doi);
            """
        )

    def save(self, result: Result) -> None:
        self.connection.execute(
            """INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(query) DO UPDATE SET
              doi=excluded.doi, title=excluded.title, status=excluded.status,
              path=excluded.path, source=excluded.source, version=excluded.version,
              sha256=excluded.sha256, error_code=excluded.error_code,
              message=excluded.message, updated_at=excluded.updated_at""",
            (
                result.query, result.doi, result.title, result.status,
                str(result.path) if result.path else None, result.source,
                result.version, result.sha256, result.error_code,
                result.message, _now(),
            ),
        )
        self.connection.commit()

    def attempt(self, query: str, candidate: Candidate, status: str, error=None) -> None:
        self.connection.execute(
            "INSERT INTO attempts (query, source, url, status, error_code, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (query, candidate.source, candidate.url, status,
             getattr(error, "code", None), str(error) if error else None, _now()),
        )
        self.connection.commit()

    def export_json(self) -> list[dict]:
        self.connection.row_factory = sqlite3.Row
        rows = self.connection.execute("SELECT * FROM results ORDER BY updated_at").fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()
