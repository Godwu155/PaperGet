import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from paperget.downloader import Downloader, filename_for_doi, filename_for_paper, pdf_is_valid
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
    def test_title_filename_is_safe_and_unique(self):
        first = filename_for_paper('A: Study / of <Cells>?', '10.1234/one')
        second = filename_for_paper('A: Study / of <Cells>?', '10.1234/two')
        self.assertTrue(first.startswith('A Study of Cells ['))
        self.assertTrue(first.endswith('.pdf'))
        self.assertNotEqual(first, second)
        self.assertEqual(filename_for_paper('', '10.1234/one'), filename_for_doi('10.1234/one'))
        self.assertLessEqual(len(filename_for_paper('😀' * 200, '10.1234/one').encode('utf-16-le')) // 2, 255)

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

    def test_download_time_limit_removes_partial_file(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            path = Path(directory) / "article.pdf"
            with patch("paperget.downloader.time.monotonic", side_effect=[0, 0, 2]):
                with self.assertRaises(PaperGetError) as raised:
                    Downloader(Http(b"%PDF-1.7\nbody"), max_seconds=1).download(
                        "https://example.org/a.pdf", path
                    )
            self.assertEqual(raised.exception.code, "timeout")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unwritable_destination_reports_disk_error_before_network(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            blocking_file = Path(directory) / "not-a-directory"
            blocking_file.write_text("occupied", encoding="utf-8")
            http = Http(b"%PDF-1.7\nbody")
            destination = blocking_file / "article.pdf"
            with self.assertRaises(PaperGetError) as raised:
                Downloader(http).download("https://example.org/a.pdf", destination)
            self.assertEqual(raised.exception.code, "disk_error")
            self.assertEqual(blocking_file.read_text(encoding="utf-8"), "occupied")

    def test_manual_import_unwritable_destination_reports_disk_error(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nbody")
            blocking_file = root / "not-a-directory"
            blocking_file.write_text("occupied", encoding="utf-8")
            with self.assertRaises(PaperGetError) as raised:
                Downloader(Http(b"")).import_file(source, blocking_file / "article.pdf")
            self.assertEqual(raised.exception.code, "disk_error")
            self.assertEqual(source.read_bytes(), b"%PDF-1.7\nbody")
