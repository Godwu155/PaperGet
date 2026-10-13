import unittest
from unittest.mock import patch

import requests

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
    def test_offline_connection_reports_connection_error(self):
        class OfflineSession:
            headers = {}

            def get(self, *_args, **_kwargs):
                raise requests.ConnectionError("offline")

        with patch("paperget.http.time.sleep"):
            with self.assertRaises(PaperGetError) as raised:
                HttpClient(OfflineSession(), min_interval=0).get(
                    "https://example.org/paper.pdf", retries=1
                )
        self.assertEqual(raised.exception.code, "connection_error")

    def test_429_skips_without_waiting_or_retrying(self):
        limited = Response(429, {"Retry-After": "900"})
        session = Session([limited])
        with patch("paperget.http.time.sleep") as sleep:
            with self.assertRaises(PaperGetError) as raised:
                HttpClient(session, min_interval=0).get("https://example.org/paper.pdf")
        self.assertEqual(raised.exception.code, "rate_limited")
        self.assertIn("900s", str(raised.exception))
        self.assertEqual(session.calls, 1)
        sleep.assert_not_called()
        self.assertTrue(limited.closed)

    def test_long_server_retry_after_skips_without_waiting(self):
        unavailable = Response(503, {"Retry-After": "900"})
        session = Session([unavailable])
        with patch("paperget.http.time.sleep") as sleep:
            with self.assertRaises(PaperGetError) as raised:
                HttpClient(session, min_interval=0).get("https://example.org/paper.pdf")
        self.assertEqual(raised.exception.code, "server_error")
        self.assertEqual(session.calls, 1)
        sleep.assert_not_called()
        self.assertTrue(unavailable.closed)

    def test_429_exhausted_reports_rate_limit(self):
        limited = Response(429)
        session = Session([limited])
        with self.assertRaises(PaperGetError) as raised:
            HttpClient(session, min_interval=0).get("https://example.org/paper.pdf", retries=0)
        self.assertEqual(raised.exception.code, "rate_limited")
        self.assertTrue(limited.closed)

    def test_403_stops_without_retry(self):
        session = Session([Response(403)])
        with self.assertRaises(PaperGetError) as raised:
            HttpClient(session, min_interval=0).get("https://example.org/paper.pdf")
        self.assertEqual(raised.exception.code, "forbidden")
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
