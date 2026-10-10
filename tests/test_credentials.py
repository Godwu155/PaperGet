import unittest
from unittest.mock import patch

from paperget import credentials


class Backend:
    def __init__(self):
        self.value = None

    def get_password(self, *_):
        return self.value

    def set_password(self, _service, _account, value):
        self.value = value

    def delete_password(self, *_):
        self.value = None


class CredentialsTests(unittest.TestCase):
    def tearDown(self):
        credentials._session_key = None
        credentials._cached_key = credentials._UNSET

    def test_save_read_and_clear(self):
        backend = Backend()
        with patch("paperget.credentials._backend", return_value=backend):
            self.assertTrue(credentials.save_openalex_key("  sample-key  "))
            self.assertEqual(credentials.get_openalex_key(), "sample-key")
            self.assertTrue(credentials.clear_openalex_key())
            self.assertIsNone(credentials.get_openalex_key())

    def test_unavailable_backend_keeps_key_only_in_memory(self):
        with patch("paperget.credentials._backend", return_value=None):
            self.assertFalse(credentials.save_openalex_key("sample-key"))
            self.assertEqual(credentials.get_openalex_key(), "sample-key")
