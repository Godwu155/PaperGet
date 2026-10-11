import tempfile
import unittest
import sqlite3
from pathlib import Path

from paperget.config import Config
from paperget.downloader import filename_for_doi, filename_for_paper
from paperget.errors import PaperGetError
from paperget.models import Paper, Result
from paperget.service import PaperGetService


DOI = "10.1371/journal.pone.0000001"


class Response:
    status_code = 200

    def __init__(self, url, *, data=None, body=b""):
        self.url = url
        self.data = data
        self.body = body
        self.headers = {"Content-Type": "application/pdf" if body else "application/json"}

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Http:
    def __init__(self, *, block_first=False):
        self.calls = []
        self.block_first = block_first

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "api.crossref.org" in url:
            return Response(url, data={"message": {"DOI": DOI, "title": ["Example paper"]}})
        if "api.openalex.org" in url:
            locations = [
                {"is_oa": True, "pdf_url": "https://example.org/first.pdf", "version": "submittedVersion"},
                {"is_oa": True, "pdf_url": "https://mirror.example.net/second.pdf", "version": "publishedVersion"},
            ]
            return Response(url, data={"best_oa_location": locations[0], "locations": locations})
        if url.endswith("first.pdf") and self.block_first:
            raise PaperGetError("forbidden", "HTTP 403")
        return Response(url, body=b"%PDF-1.7\nexample content")


class ServiceTests(unittest.TestCase):
    def test_missing_pdf_explains_disabled_fallback(self):
        class NoPdf(Http):
            def get(self, url, **kwargs):
                if "api.openalex.org" in url:
                    return Response(url, data={"best_oa_location": None, "locations": []})
                return super().get(url, **kwargs)

        with tempfile.TemporaryDirectory(dir=".") as directory:
            with PaperGetService(Config(output_dir=Path(directory)), http=NoPdf()) as service:
                result = service.fetch(DOI)
                self.assertEqual((result.status, result.error_code), ("not_found", "no_pdf"))
                self.assertIn("--scihub-url", result.message)
                events = service.store.diagnostics(DOI)
                self.assertEqual([(row["source"], row["status"]) for row in events],
                                 [("scihub", "disabled"), ("openalex", "empty")])

    def test_fallback_and_existing_file(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            http = Http(block_first=True)
            with PaperGetService(Config(output_dir=Path(directory)), http=http) as service:
                result = service.fetch(DOI)
                self.assertEqual((result.status, result.source), ("downloaded", "openalex"))
                self.assertTrue(result.path.is_file())
                self.assertEqual(result.path.name, filename_for_paper("Example paper", DOI))
                self.assertEqual(result.path.read_bytes()[:5], b"%PDF-")
                before = len(http.calls)
                again = service.fetch(DOI)
                self.assertEqual(again.status, "existing")
                self.assertEqual(again.source, "openalex")
                self.assertEqual(len(http.calls), before)
                attempts = service.store.connection.execute("SELECT status FROM attempts ORDER BY id").fetchall()
                self.assertEqual([row[0] for row in attempts], ["failed", "downloaded"])
                events = service.store.diagnostics(DOI)
                self.assertTrue(any(row["stage"] == "download" and row["error_code"] == "forbidden"
                                    for row in events))
                self.assertTrue(any(row["stage"] == "download" and row["status"] == "downloaded"
                                    for row in events))

    def test_import_local_pdf_validates_and_records_manual_source(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            source = root / "picked.pdf"
            source.write_bytes(b"%PDF-1.7\nmanual content")
            with PaperGetService(Config(output_dir=root / "output"), http=Http()) as service:
                service.store.save(Result(query=DOI, status="not_found", doi=DOI, title="Example paper"))
                result = service.import_pdf(DOI, source)
                self.assertEqual((result.status, result.source), ("downloaded", "manual"))
                self.assertTrue(result.path.is_file())
                self.assertEqual(result.path.name, filename_for_paper("Example paper", DOI))
                self.assertEqual(service.import_pdf(DOI, source).status, "existing")
                self.assertEqual(service.store.diagnostics(DOI)[0]["stage"], "import")

    def test_import_local_pdf_rejects_html_without_target_file(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            source = root / "fake.pdf"
            source.write_text("<html>not a PDF</html>", encoding="utf-8")
            with PaperGetService(Config(output_dir=root / "output"), http=Http()) as service:
                result = service.import_pdf(DOI, source)
                self.assertEqual((result.status, result.error_code), ("failed", "invalid_pdf"))
                self.assertFalse(list((root / "output").glob("*.pdf")))
                self.assertEqual(service.store.diagnostics(DOI)[0]["error_code"], "invalid_pdf")

    def test_diagnostic_messages_redact_urls(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            with PaperGetService(Config(output_dir=Path(directory)), http=Http()) as service:
                service._event("run", DOI, DOI, "openalex", "download", "failed",
                               error_code="connection_error",
                               message="Failed https://example.org/file.pdf?token=private")
                message = service.store.diagnostics(DOI)[0]["message"]
                self.assertIn("[URL]", message)
                self.assertNotIn("private", message)

    def test_legacy_doi_filename_is_reused(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            old_path = Path(directory) / filename_for_doi(DOI)
            old_path.write_bytes(b"%PDF-1.7\nlegacy")
            http = Http()
            with PaperGetService(Config(output_dir=Path(directory)), http=http) as service:
                result = service.fetch(DOI)
                self.assertEqual(result.status, "existing")
                self.assertEqual(result.path, old_path)
                self.assertFalse(any(url.endswith(".pdf") for url in http.calls))

    def test_recorded_file_is_reused_if_metadata_title_changes(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            http = Http()
            with PaperGetService(Config(output_dir=Path(directory)), http=http) as service:
                first = service.fetch(DOI)
                before = len(http.calls)
                service.resolver.resolve = lambda *_args, **_kwargs: Paper(doi=DOI, title="Revised title")
                again = service.fetch(DOI)
                self.assertEqual(again.status, "existing")
                self.assertEqual(again.path, first.path)
                self.assertEqual(len(http.calls), before)

    def test_openalex_title_fills_missing_crossref_title(self):
        class MetadataHttp(Http):
            def get(self, url, **kwargs):
                response = super().get(url, **kwargs)
                if "api.crossref.org" in url:
                    response.data["message"]["title"] = []
                if "api.openalex.org" in url:
                    response.data["title"] = "OpenAlex: Paper / Title"
                return response

        with tempfile.TemporaryDirectory(dir=".") as directory:
            with PaperGetService(Config(output_dir=Path(directory)), http=MetadataHttp()) as service:
                result = service.fetch(DOI)
                self.assertEqual(result.status, "downloaded")
                self.assertEqual(result.title, "OpenAlex: Paper / Title")
                self.assertEqual(result.path.name, filename_for_paper(result.title, DOI))

    def test_inspect_uses_metadata_cache_and_does_not_download(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            http = Http()
            with PaperGetService(Config(output_dir=Path(directory)), http=http) as service:
                for _ in range(2):
                    result = service.fetch(DOI, inspect=True)
                    self.assertEqual(result.status, "found")
                    self.assertEqual(len(result.candidates), 2)
                self.assertEqual(len(http.calls), 2)
                self.assertFalse(list(Path(directory).glob("*.pdf")))

    def test_forbidden_is_reported_without_pdf(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            http = Http(block_first=True)
            with PaperGetService(Config(output_dir=Path(directory), prefer_published=False), http=http) as service:
                http.block_first = True
                # Make every candidate unavailable, including the second one.
                original = http.get

                def denied(url, **kwargs):
                    if url.endswith(".pdf"):
                        raise PaperGetError("forbidden", "HTTP 403")
                    return original(url, **kwargs)

                http.get = denied
                result = service.fetch(DOI)
                self.assertEqual((result.status, result.error_code), ("failed", "forbidden"))
                self.assertFalse(list(Path(directory).glob("*.pdf")))

    def test_published_version_is_tried_first_when_requested(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            http = Http(block_first=True)
            with PaperGetService(Config(output_dir=Path(directory), prefer_published=True), http=http) as service:
                result = service.fetch(DOI)
                self.assertEqual(result.status, "downloaded")
                self.assertEqual(result.version, "publishedVersion")
                self.assertNotIn("https://example.org/first.pdf", http.calls)

    def test_database_write_failure_does_not_lose_download(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            with PaperGetService(Config(output_dir=Path(directory)), http=Http()) as service:
                def unavailable(_result):
                    raise sqlite3.OperationalError("read only")

                service.store.save = unavailable
                result = service.fetch(DOI)
                self.assertEqual(result.status, "downloaded")
                self.assertTrue(result.path.is_file())
                self.assertIn("database unavailable", result.message.lower())


if __name__ == "__main__":
    unittest.main()
