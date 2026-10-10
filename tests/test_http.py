import unittest

from paperget.errors import PaperGetError
from paperget.http import HttpClient


class Response:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.headers = {}
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return next(self.responses)


class HttpTests(unittest.TestCase):
    def test_429_retries_after_header(self):
        limited = Response(429, {"Retry-After": "0"})
        session = Session([limited, Response(200)])
        response = HttpClient(session, min_interval=0).get("https://example.org/paper.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 2)
        self.assertTrue(limited.closed)

    def test_403_stops_without_retry(self):
        session = Session([Response(403)])
        with self.assertRaises(PaperGetError) as raised:
            HttpClient(session, min_interval=0).get("https://example.org/paper.pdf")
        self.assertEqual(raised.exception.code, "forbidden")
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
