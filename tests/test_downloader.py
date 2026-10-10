import tempfile
import unittest
from pathlib import Path

import requests

from paperget.downloader import Downloader, filename_for_doi, pdf_is_valid
from paperget.errors import PaperGetError


class Response:
    status_code = 200
    headers = {}

    def __init__(self, body):
        self.body = body

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Http:
    def __init__(self, body):
        self.body = body

    def get(self, *_args, **_kwargs):
        return Response(self.body)


class DownloaderTests(unittest.TestCase):
    def test_valid_pdf_and_duplicate(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            path = Path(directory) / filename_for_doi("10.1234/a/b")
            downloader = Downloader(Http(b"%PDF-1.7\nbody"))
            first_hash = downloader.download("https://example.org/a.pdf", path)
            self.assertTrue(pdf_is_valid(path))
            self.assertEqual(downloader.download("https://example.org/a.pdf", path), first_hash)

    def test_html_is_rejected_and_temp_removed(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            path = Path(directory) / "article.pdf"
            with self.assertRaises(PaperGetError) as raised:
                Downloader(Http(b"<html>Not a PDF</html>")).download("https://example.org/a.pdf", path)
            self.assertEqual(raised.exception.code, "invalid_pdf")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_interrupted_download_leaves_no_partial_file(self):
        class Interrupted(Response):
            def iter_content(self, chunk_size):
                yield b"%PDF-1.7\npartial"
                raise requests.ConnectionError("connection lost")

        class InterruptedHttp:
            def get(self, *_args, **_kwargs):
                return Interrupted(b"")

        with tempfile.TemporaryDirectory(dir=".") as directory:
            path = Path(directory) / "article.pdf"
            with self.assertRaises(PaperGetError) as raised:
                Downloader(InterruptedHttp()).download("https://example.org/a.pdf", path)
            self.assertEqual(raised.exception.code, "connection_error")
            self.assertEqual(list(Path(directory).iterdir()), [])
