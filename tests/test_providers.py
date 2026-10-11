import unittest
from pathlib import Path

from paperget.errors import PaperGetError
from paperget.models import Paper
from paperget.providers.openalex import OpenAlexProvider
from paperget.providers.scihub import SciHubProvider, _PdfLinks


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

    def test_openalex_404_has_distinct_reason(self):
        class NotFound:
            status_code = 404

            def close(self):
                pass

        class Site:
            def get(self, *_args, **_kwargs):
                return NotFound()

        provider = OpenAlexProvider(Site())
        self.assertEqual(provider.find(Paper("10.1234/missing")), [])
        self.assertEqual(provider.last_empty_reason, "work_not_found")

    def test_scihub_html_parser_extracts_embedded_pdf(self):
        parser = _PdfLinks()
        parser.feed('<iframe src="//example.org/article.pdf"></iframe><a href="/about">About</a>')
        self.assertEqual(parser.links, ["//example.org/article.pdf"])

    def test_scihub_ignores_ads_and_hidden_template_links(self):
        parser = _PdfLinks()
        parser.feed((Path(__file__).parent / "fixtures" / "scihub_available.html").read_text(encoding="utf-8"))
        self.assertEqual(parser.links, ["https://sci.bban.top/pdf/10.1128/AEM.01532-09.pdf"])

    def test_scihub_unavailable_page_has_no_candidate(self):
        class Page:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            url = "https://sci-hub.al/10.1234/absent"
            text = (Path(__file__).parent / "fixtures" / "scihub_unavailable.html").read_text(encoding="utf-8")

            def close(self):
                pass

        class Site:
            def get(self, *_args, **_kwargs):
                return Page()

        provider = SciHubProvider(Site(), "https://sci-hub.al/")
        found = provider.find(Paper("10.1234/absent"))
        self.assertEqual(found, [])
        self.assertEqual(provider.last_empty_reason, "no_pdf_link")

    def test_scihub_rejects_page_for_different_doi(self):
        class Page:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            url = "https://sci-hub.al/10.1234/requested"
            text = '<div id="citation">doi:10.1234/different</div><embed id="pdf" src="https://example.org/paper.pdf">'

            def close(self):
                pass

        class Site:
            def get(self, *_args, **_kwargs):
                return Page()

        self.assertEqual(SciHubProvider(Site(), "https://sci-hub.al/").find(Paper("10.1234/requested")), [])

    def test_scihub_challenge_page_is_distinct_from_missing_pdf(self):
        class Page:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            url = "https://sci-hub.al/10.1234/example"
            text = "<html><body>Verify you are human to continue</body></html>"

            def close(self):
                pass

        class Site:
            def get(self, *_args, **_kwargs):
                return Page()

        with self.assertRaises(PaperGetError) as raised:
            SciHubProvider(Site(), "https://sci-hub.al/").find(Paper("10.1234/example"))
        self.assertEqual(raised.exception.code, "challenge_required")
