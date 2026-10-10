import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from paperget.gui_window import MainWindow, _config
except ImportError:
    QApplication = None

from paperget.models import Candidate, Result, SearchResult, TitleMatch


@unittest.skipUnless(QApplication is not None, "PySide6 GUI extra is not installed")
class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.processEvents()
        cls.app.quit()
        cls.app = None

    def wait_idle(self, window):
        for _ in range(200):
            self.app.processEvents()
            if window._thread is None:
                return
            time.sleep(0.01)
        self.fail("GUI worker did not finish")

    def test_gui_settings_require_explicit_scihub_enable(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.IniFormat)
            with patch.dict(os.environ, {"SCIHUB_BASE_URL": "https://example.org/"}):
                config = _config(settings)
                self.assertIsNone(config.scihub_base_url)
                self.assertEqual(config.source_order, ("openalex",))
                settings.setValue("scihub_enabled", True)
                settings.setValue("scihub_url", "https://example.org/")
                settings.setValue("source_order", "scihub,openalex")
                config = _config(settings)
                self.assertEqual(config.scihub_base_url, "https://example.org/")
                self.assertEqual(config.source_order, ("scihub", "openalex"))
            settings.sync()
            del settings

    def test_search_candidate_inspect_and_download_queue(self):
        calls = []

        def fake_perform(task, _config):
            calls.append((task.kind, task.query))
            if task.kind == "history":
                return []
            if task.kind == "search":
                return SearchResult(task.query, "found", [TitleMatch(
                    "10.1234/example", "Example Paper", 2024, ("A. Author",), 0.91,
                )])
            if task.kind == "inspect":
                return Result(task.query, "found", doi=task.query, title="Example Paper",
                              candidates=[Candidate("https://example.org/paper.pdf", "openalex")])
            if task.kind == "download":
                return Result(task.query, "downloaded", doi=task.query, title="Example Paper",
                              source="openalex")
            raise AssertionError(task.kind)

        with patch("paperget.gui_window.perform", side_effect=fake_perform):
            window = MainWindow()
            self.wait_idle(window)
            window.query.setText("Example")
            window._search()
            self.wait_idle(window)
            self.assertEqual(window.candidates.rowCount(), 1)
            window.candidates.selectRow(0)
            self.wait_idle(window)
            self.assertEqual(window.selected_doi, "10.1234/example")
            self.assertEqual(window.source_table.rowCount(), 1)
            window._enqueue_selected()
            for _ in range(200):
                self.app.processEvents()
                if window._thread is None and window.queue_table.item(0, 1).text() == "已下载":
                    break
                time.sleep(0.01)
            self.wait_idle(window)
            self.assertEqual(window.queue_table.item(0, 1).text(), "已下载")
            self.assertEqual([kind for kind, _ in calls[:4]], ["history", "search", "inspect", "download"])
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_failed_download_does_not_stop_pending_queue(self):
        def fake_perform(task, _config):
            if task.kind == "history":
                return []
            if task.kind == "download":
                time.sleep(0.03)
                if task.query.endswith("bad"):
                    return Result(task.query, "failed", error_code="invalid_pdf", message="HTML response")
                return Result(task.query, "downloaded", doi=task.query, source="openalex")
            raise AssertionError(task.kind)

        with patch("paperget.gui_window.perform", side_effect=fake_perform):
            window = MainWindow()
            self.wait_idle(window)
            window._enqueue("10.1234/bad")
            window._enqueue("10.1234/good")
            window.query.setText("Window remains responsive")
            for _ in range(300):
                self.app.processEvents()
                if (window._thread is None and not window.pending and
                        window.queue_table.item(1, 1).text() == "已下载"):
                    break
                time.sleep(0.01)
            self.assertEqual(window.queue_table.item(0, 1).text(), "失败")
            self.assertEqual(window.queue_table.item(1, 1).text(), "已下载")
            self.assertEqual(window.query.text(), "Window remains responsive")
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
