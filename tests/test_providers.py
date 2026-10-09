import unittest

from paperget.models import Paper
from paperget.providers.openalex import OpenAlexProvider
from paperget.providers.scihub import _PdfLinks


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def close(self):
        pass


class Http:
    def __init__(self, data):
        self.data = data

    def get(self, *_args, **_kwargs):
        return Response(self.data)


class ProviderTests(unittest.TestCase):
    def test_openalex_deduplicates_open_pdf_locations(self):
        location = {"is_oa": True, "pdf_url": "https://example.org/article.pdf", "version": "publishedVersion"}
        work = {"best_oa_location": location, "locations": [location, {"is_oa": False, "pdf_url": "https://example.org/closed.pdf"}]}
        found = OpenAlexProvider(Http(work)).find(Paper("10.1234/example"))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].version, "publishedVersion")

    def test_scihub_html_parser_extracts_embedded_pdf(self):
        parser = _PdfLinks()
        parser.feed('<iframe src="//example.org/article.pdf"></iframe><a href="/about">About</a>')
        self.assertEqual(parser.links, ["//example.org/article.pdf"])
