import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperget.cli import main


DOI = "10.1371/journal.pone.0000001"


class Response:
    status_code = 200

    def __init__(self, url, *, data=None, body=b"", invalid=False):
        self.url = url
        self.data = data
        self.body = body
        self.invalid = invalid
        self.headers = {"Content-Type": "application/pdf" if body else "application/json"}

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
        return Response(url, body=b"%PDF-1.7\nexample content")


class CliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
