from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .config import Config
from .models import Paper, Result
from .service import PaperGetService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperget", description="Find and download research papers by DOI or title")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("get", "batch", "inspect"):
        entry = sub.add_parser(command)
        if command == "batch":
            entry.add_argument("file", type=Path, help="UTF-8 TXT or CSV input")
            entry.add_argument("--column", default="doi_or_title", help="CSV column containing a DOI or title")
        else:
            entry.add_argument("query", nargs="?", help="DOI or title")
            entry.add_argument("--title", help="Explicitly provide a paper title")
        entry.add_argument("--output", type=Path, default=Path("downloads"))
        entry.add_argument("--source-order", default="openalex,scihub")
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    source_order = tuple(s.strip() for s in args.source_order.split(",") if s.strip())
    if not source_order or any(s not in {"openalex", "scihub"} for s in source_order):
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
    config = Config.from_env(
        output_dir=args.output, source_order=source_order,
        prefer_published=args.prefer_published, force=args.force,
        non_interactive=args.non_interactive or args.command == "batch" or not sys.stdin.isatty(),
    )
    results: list[Result] = []
    with PaperGetService(config) as service:
        for query in queries:
            result = service.fetch(
                query, inspect=args.command == "inspect",
                choose=None if config.non_interactive else _choose,
            )
            results.append(result)
            _print(result, args.json)
    successes = {"downloaded", "existing", "found"}
    ok = sum(result.status in successes for result in results)
    return 0 if ok == len(results) else 3 if ok == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
