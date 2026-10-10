from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

from .config import Config
from .models import Paper, Result
from .service import PaperGetService
from .store import Store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperget", description="Find and download research papers by DOI or title")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("get", "batch", "inspect", "export"):
        entry = sub.add_parser(command)
        if command == "export":
            entry.add_argument("--output", type=Path, default=Path("downloads"))
            entry.add_argument("--format", choices=("json", "csv"), default="json")
            entry.add_argument("--file", type=Path, help="Output report path (default: output directory)")
            continue
        if command == "batch":
            entry.add_argument("file", type=Path, help="UTF-8 TXT or CSV input")
            entry.add_argument("--column", default="doi_or_title", help="CSV column containing a DOI or title")
            entry.add_argument("--report", type=Path, help="Write this batch's results to JSON or CSV")
        else:
            entry.add_argument("query", nargs="?", help="DOI or title")
            entry.add_argument("--title", help="Explicitly provide a paper title")
        entry.add_argument("--output", type=Path, default=Path("downloads"))
        entry.add_argument("--source-order", default="openalex,scihub")
        entry.add_argument("--scihub-url", help="Enable the optional Sci-Hub fallback for this run")
        entry.add_argument("--prefer-published", action="store_true")
        entry.add_argument("--non-interactive", action="store_true")
        entry.add_argument("--json", action="store_true", help="Print one JSON object per query")
        entry.add_argument("--force", action="store_true", help="Replace existing PDFs")
    return parser


def _choose(papers: list[Paper]) -> int | None:
    print("Multiple title matches. Choose a paper:", file=sys.stderr)
    for number, paper in enumerate(papers, 1):
        print(f"  {number}. {paper.title} ({paper.year or '?'}) — {paper.doi}", file=sys.stderr)
    print("  0. Skip", file=sys.stderr)
    try:
        value = input("Selection: ").strip()
        number = int(value)
        return number - 1 if 1 <= number <= len(papers) else None
    except (ValueError, EOFError):
        return None


def _queries(file: Path, column: str):
    if file.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("input file must be .txt or .csv")
    if file.suffix.lower() == ".csv":
        with file.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or column not in reader.fieldnames:
                raise ValueError(f"CSV column not found: {column}")
            for row in reader:
                value = (row.get(column) or "").strip()
                if value:
                    yield value
    else:
        with file.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                value = line.strip()
                if value and not value.startswith("#"):
                    yield value


def _print(result: Result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        label = f"{result.status}: {result.query}"
        if result.path:
            label += f" -> {result.path}"
        if result.message:
            label += f" ({result.message})"
        print(label)
        for candidate in result.candidates:
            print(f"  {candidate.source} {candidate.version or 'unknown version'} {candidate.url}")


def _write_report(path: Path, rows: list[dict], format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        fields = ["query", "doi", "title", "status", "path", "source", "version", "sha256", "error_code", "message"]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "export":
        path = args.file or args.output / f"paperget-results.{args.format}"
        database = args.output / "paperget.sqlite3"
        if not database.is_file():
            parser.error(f"result database not found: {database}")
        try:
            with Store(database) as store:
                _write_report(path, store.export_json(), args.format)
        except (OSError, sqlite3.Error) as exc:
            parser.error(str(exc))
        print(path)
        return 0
    source_order = tuple(s.strip() for s in args.source_order.split(",") if s.strip())
    if not source_order or len(set(source_order)) != len(source_order) or any(s not in {"openalex", "scihub"} for s in source_order):
        parser.error("--source-order must contain openalex and/or scihub")
    if args.command != "batch":
        if bool(args.query) == bool(args.title):
            parser.error("provide one query or --title")
        queries = [args.title or args.query]
    else:
        try:
            queries = list(_queries(args.file, args.column))
        except (OSError, UnicodeError, ValueError) as exc:
            parser.error(str(exc))
        if not queries:
            parser.error("input file has no queries")
        if args.report and args.report.suffix.lower() not in {".json", ".csv"}:
            parser.error("--report must end in .json or .csv")
    config_options = dict(
        output_dir=args.output, source_order=source_order,
        prefer_published=args.prefer_published, force=args.force,
        non_interactive=args.non_interactive or args.command == "batch" or not sys.stdin.isatty(),
    )
    if args.scihub_url:
        config_options["scihub_base_url"] = args.scihub_url
    config = Config.from_env(**config_options)
    if config.scihub_base_url:
        parsed = urlparse(config.scihub_base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            parser.error("Sci-Hub URL must be HTTPS with a host name")
    if source_order == ("scihub",) and not config.scihub_base_url:
        parser.error("SCIHUB_BASE_URL is required when Sci-Hub is the only source")
    results: list[Result] = []
    with PaperGetService(config) as service:
        for query in queries:
            result = service.fetch(
                query, inspect=args.command == "inspect",
                choose=None if config.non_interactive else _choose,
            )
            results.append(result)
            _print(result, args.json)
    if args.command == "batch":
        try:
            if args.report:
                _write_report(args.report, [result.to_dict() for result in results], args.report.suffix.lower()[1:])
            ambiguous = [result.to_dict() for result in results if result.status == "ambiguous"]
            if ambiguous:
                _write_report(args.output / "needs-review.json", ambiguous, "json")
        except OSError as exc:
            print(f"Failed to write report: {exc}", file=sys.stderr)
            return 1
    successes = {"downloaded", "existing", "found"}
    ok = sum(result.status in successes for result in results)
    return 0 if ok == len(results) else 3 if ok == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
