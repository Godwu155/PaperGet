import unittest
import tempfile
from pathlib import Path

from paperget.errors import PaperGetError
from paperget.resolver import Resolver, normalize_doi, search_score, title_score
from paperget.store import Store


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
        self.calls = []

    def get(self, *_args, **kwargs):
        self.calls.append(kwargs)
        return Response(self.data)


class ResolverTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(normalize_doi("https://doi.org/10.7717/PeerJ.4375"), "10.7717/peerj.4375")
        self.assertIsNone(normalize_doi("some paper title"))

    def test_title_score(self):
        self.assertEqual(title_score("A study of cells", "A study of cells"), 1.0)
        self.assertLess(title_score("A study of cells", "The economics of cities"), 0.5)

    def test_search_score_handles_partial_reordered_title(self):
        title = "Single-cell RNA-Seq profiling of human preimplantation embryos and embryonic stem cells"
        self.assertGreater(search_score("embryos human preimplantation", title), 0.7)
        self.assertGreater(search_score("embryos human preimplantation", title), search_score("urban economics", title))

    def test_search_returns_ranked_unique_candidates_and_caches_by_limit(self):
        data = {"message": {"items": [
            {"DOI": "10.1234/one", "title": ["Human preimplantation embryos"],
             "published": {"date-parts": [[2013]]}, "author": [{"given": "Liying", "family": "Yan"}]},
            {"DOI": "10.1234/ONE", "title": ["Human preimplantation embryos"]},
            {"DOI": "", "title": ["Human preimplantation embryos"]},
            {"DOI": "10.1234/two", "title": ["Urban economics"]},
        ]}}
        http = Http(data)
        with tempfile.TemporaryDirectory(dir=".") as directory, Store(Path(directory) / "cache.sqlite3") as store:
            resolver = Resolver(http, cache=store)
            matches = resolver.search_title("preimplantation human embryos", limit=10)
            self.assertEqual([match.doi for match in matches], ["10.1234/one", "10.1234/two"])
            self.assertEqual((matches[0].year, matches[0].authors), (2013, ("Liying Yan",)))
            self.assertEqual(matches[0].to_dict()["doi_url"], "https://doi.org/10.1234/one")
            resolver.search_title("preimplantation human embryos", limit=10)
            self.assertEqual(len(http.calls), 1)
            self.assertEqual(http.calls[0]["params"]["rows"], 10)
            resolver.search_title("preimplantation human embryos", limit=5)
            self.assertEqual(len(http.calls), 2)

    def test_title_resolves_clear_match(self):
        data = {"message": {"items": [
            {"DOI": "10.1234/exact", "title": ["A study of cells"]},
            {"DOI": "10.1234/other", "title": ["The economics of cities"]},
        ]}}
        paper = Resolver(Http(data)).resolve("A study of cells")
        self.assertEqual(paper.doi, "10.1234/exact")

    def test_ambiguous_title_requires_choice(self):
        data = {"message": {"items": [
            {"DOI": "10.1234/one", "title": ["A study of cells"]},
            {"DOI": "10.1234/two", "title": ["A study of cells"]},
        ]}}
        with self.assertRaises(PaperGetError) as raised:
            Resolver(Http(data)).resolve("A study of cells")
        self.assertEqual(raised.exception.code, "ambiguous_title")
        selected = Resolver(Http(data)).resolve("A study of cells", choose=lambda _: 1)
        self.assertEqual(selected.doi, "10.1234/two")
