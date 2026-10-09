import unittest

from paperget.errors import PaperGetError
from paperget.resolver import Resolver, normalize_doi, title_score


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


class ResolverTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(normalize_doi("https://doi.org/10.7717/PeerJ.4375"), "10.7717/peerj.4375")
        self.assertIsNone(normalize_doi("some paper title"))

    def test_title_score(self):
        self.assertEqual(title_score("A study of cells", "A study of cells"), 1.0)
        self.assertLess(title_score("A study of cells", "The economics of cities"), 0.5)

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
