from __future__ import annotations

import json
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
            CREATE TABLE IF NOT EXISTS files (
                doi TEXT PRIMARY KEY, path TEXT NOT NULL, source TEXT,
                version TEXT, sha256 TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                query TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
                version TEXT, license TEXT, landing_page_url TEXT,
                discovered_at TEXT NOT NULL, PRIMARY KEY (query, source, url)
            );
            CREATE TABLE IF NOT EXISTS metadata_cache (
                source TEXT NOT NULL, query TEXT NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY (source, query)
            );
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
        if result.status == "downloaded" and result.doi and result.path and result.sha256:
            self.connection.execute(
                """INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doi) DO UPDATE SET path=excluded.path, source=excluded.source,
                  version=excluded.version, sha256=excluded.sha256, updated_at=excluded.updated_at""",
                (result.doi, str(result.path), result.source, result.version, result.sha256, _now()),
            )
        self.connection.commit()

    def file_info(self, doi: str) -> tuple[str | None, str | None] | None:
        try:
            row = self.connection.execute("SELECT source, version FROM files WHERE doi=?", (doi,)).fetchone()
            return (row[0], row[1]) if row else None
        except sqlite3.Error:
            return None

    def attempt(self, query: str, candidate: Candidate, status: str, error=None) -> None:
        self.connection.execute(
            "INSERT INTO attempts (query, source, url, status, error_code, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (query, candidate.source, candidate.url, status,
             getattr(error, "code", None), str(error) if error else None, _now()),
        )
        self.connection.commit()

    def record_candidates(self, query: str, candidates: list[Candidate]) -> None:
        self.connection.executemany(
            """INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(query, source, url) DO UPDATE SET
              version=excluded.version, license=excluded.license,
              landing_page_url=excluded.landing_page_url,
              discovered_at=excluded.discovered_at""",
            [(query, c.source, c.url, c.version, c.license, c.landing_page_url, _now()) for c in candidates],
        )
        self.connection.commit()

    def export_json(self) -> list[dict]:
        self.connection.row_factory = sqlite3.Row
        rows = self.connection.execute("SELECT * FROM results ORDER BY updated_at").fetchall()
        return [dict(row) for row in rows]

    def cached(self, source: str, query: str, max_age_seconds: int = 604800) -> dict | None:
        try:
            row = self.connection.execute(
                "SELECT payload, updated_at FROM metadata_cache WHERE source=? AND query=?",
                (source, query),
            ).fetchone()
            if row is None:
                return None
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row[1])
            return json.loads(row[0]) if age.total_seconds() <= max_age_seconds else None
        except (sqlite3.Error, ValueError, TypeError):
            return None

    def cache(self, source: str, query: str, payload: dict) -> None:
        try:
            self.connection.execute(
                """INSERT INTO metadata_cache VALUES (?, ?, ?, ?)
                ON CONFLICT(source, query) DO UPDATE SET
                  payload=excluded.payload, updated_at=excluded.updated_at""",
                (source, query, json.dumps(payload, ensure_ascii=False), _now()),
            )
            self.connection.commit()
        except (sqlite3.Error, TypeError, ValueError):
            pass

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
