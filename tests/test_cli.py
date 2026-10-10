import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperget.cli import main
from paperget.errors import PaperGetError


DOI = "10.1371/journal.pone.0000001"


class Response:
    status_code = 200

    def __init__(self, url, *, data=None, body=b"", invalid=False, text=""):
        self.url = url
        self.data = data
        self.body = body
        self.invalid = invalid
        self.text = text
        self.headers = {"Content-Type": "text/html" if text else "application/pdf" if body else "application/json"}

    def json(self):
        if self.invalid:
            raise ValueError("bad JSON")
        return self.data

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Http:
    def get(self, url, **kwargs):
        if "api.crossref.org/works/" in url:
            return Response(url, data={"message": {"DOI": DOI, "title": ["Example paper"]}})
        if "api.crossref.org/works" in url:
            return Response(url, invalid=True)
        if "api.openalex.org" in url:
            location = {"is_oa": True, "pdf_url": "https://example.org/article.pdf"}
            return Response(url, data={"best_oa_location": location, "locations": [location]})
        if "sci-hub.al" in url:
            return Response(url, text='<div id="citation">doi:10.1371/journal.pone.0000001</div><embed id="pdf" src="https://example.org/article.pdf">')
        return Response(url, body=b"%PDF-1.7\nexample content")


class SearchHttp:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url != "https://api.crossref.org/works":
            raise AssertionError(f"search tried a non-metadata URL: {url}")
        return Response(url, data={"message": {"items": self.items}})


class CliTests(unittest.TestCase):
    def test_search_json_lists_candidates_without_downloading(self):
        items = [
            {"DOI": "10.1234/first", "title": ["Human preimplantation embryos"], "author": [{"family": "Yan"}]},
            {"DOI": "10.1234/second", "title": ["Economics of cities"]},
        ]
        with tempfile.TemporaryDirectory(dir=".") as directory:
            output = io.StringIO()
            http = SearchHttp(items)
            with patch("paperget.service.HttpClient", return_value=http), contextlib.redirect_stdout(output):
                code = main(["search", "preimplantation human embryos", "--limit", "2", "--json", "--output", directory])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual((result["status"], result["count"]), ("found", 2))
            self.assertEqual(result["candidates"][0]["doi"], "10.1234/first")
            self.assertEqual(http.calls, ["https://api.crossref.org/works"])
            self.assertFalse(list(Path(directory).glob("*.pdf")))

    def test_search_empty_result_and_invalid_limit(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            output = io.StringIO()
            with patch("paperget.service.HttpClient", return_value=SearchHttp([])), contextlib.redirect_stdout(output):
                code = main(["search", "unfindable title", "--json", "--output", directory])
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(output.getvalue())["status"], "not_found")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["search", "title", "--limit", "0"])
        self.assertEqual(raised.exception.code, 2)

    def test_search_reports_metadata_failure(self):
        class RateLimited:
            def get(self, *_args, **_kwargs):
                raise PaperGetError("rate_limited", "Crossref HTTP 429")

        with tempfile.TemporaryDirectory(dir=".") as directory:
            output = io.StringIO()
            with patch("paperget.service.HttpClient", return_value=RateLimited()), contextlib.redirect_stdout(output):
                code = main(["search", "human embryos", "--json", "--output", directory])
            self.assertEqual(code, 3)
            result = json.loads(output.getvalue())
            self.assertEqual((result["status"], result["error_code"]), ("failed", "rate_limited"))

    def test_search_handles_titles_outside_console_encoding(self):
        items = [{"DOI": "10.1234/symbol", "title": ["Embryos 🙂 study"]}]
        with tempfile.TemporaryDirectory(dir=".") as directory:
            raw = io.BytesIO()
            console = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
            with patch("paperget.service.HttpClient", return_value=SearchHttp(items)), contextlib.redirect_stdout(console):
                code = main(["search", "embryos", "--output", directory])
            console.flush()
            self.assertEqual(code, 0)
            self.assertIn("Embryos \\U0001f642 study", raw.getvalue().decode("gbk"))

    def test_scihub_url_requires_https(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["get", DOI, "--scihub-url", "http://sci-hub.al/"])
        self.assertEqual(raised.exception.code, 2)

    def test_batch_continues_after_invalid_title_response_and_exports_results(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            source = root / "papers.txt"
            source.write_text(f"{DOI}\nA title with a broken response\n{DOI}\n", encoding="utf-8")
            output = root / "downloads"
            report = root / "report.json"
            with patch("paperget.service.HttpClient", return_value=Http()), contextlib.redirect_stdout(io.StringIO()):
                code = main(["batch", str(source), "--output", str(output), "--report", str(report)])
            self.assertEqual(code, 1)
            rows = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual([row["status"] for row in rows], ["downloaded", "failed", "existing"])
            self.assertEqual(rows[1]["error_code"], "invalid_response")
            self.assertEqual(len(list(output.glob("*.pdf"))), 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["export", "--output", str(output), "--file", str(root / "all.csv"), "--format", "csv"]), 0)
            self.assertIn("invalid_response", (root / "all.csv").read_text(encoding="utf-8-sig"))

    def test_scihub_url_enables_fallback_for_one_command(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            with patch("paperget.service.HttpClient", return_value=Http()), contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "get", DOI, "--source-order", "scihub",
                    "--scihub-url", "https://sci-hub.al/", "--output", directory,
                ])
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(directory).glob("*.pdf"))), 1)


if __name__ == "__main__":
    unittest.main()
