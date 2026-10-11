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
    from paperget.gui_window import BatchPreviewDialog, MainWindow, SettingsDialog, _config
    from paperget.gui_backend import Task
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

    def test_settings_dialog_saves_preferences_without_keys(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            dialog = SettingsDialog(settings, None)
            dialog.output.setText(str(root / "papers"))
            dialog.maximum.setValue(75)
            dialog.source_order.setCurrentIndex(1)
            dialog.scihub.setChecked(True)
            dialog.scihub_url.setText("https://example.org/")
            dialog._save()
            self.assertEqual(dialog.result(), SettingsDialog.Accepted)
            self.assertTrue((root / "papers").is_dir())
            self.assertEqual(settings.value("max_pdf_mb", type=int), 75)
            self.assertEqual(settings.value("source_order"), "scihub,openalex")
            self.assertNotIn("API_KEY", (root / "settings.ini").read_text(encoding="utf-8"))
            dialog.deleteLater()
            self.app.processEvents()
            settings.sync()
            del dialog, settings

    def test_gui_key_and_crossref_email_settings(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            with patch("paperget.gui_window.get_openalex_key", return_value=None), \
                 patch("paperget.gui_window.save_openalex_key", return_value=True) as save:
                dialog = SettingsDialog(settings, None)
                dialog.output.setText(str(root / "papers"))
                dialog.openalex_key.setText("secret-key")
                dialog.crossref_mailto.setText("reader@example.org")
                dialog._save()
                self.assertEqual(dialog.result(), SettingsDialog.Accepted)
                save.assert_called_once_with("secret-key")
                dialog.deleteLater()
                self.app.processEvents()
            with patch("paperget.gui_window.get_openalex_key", return_value="secret-key"):
                config = _config(settings)
            self.assertEqual(config.openalex_api_key, "secret-key")
            self.assertEqual(config.crossref_mailto, "reader@example.org")
            settings.sync()
            self.assertNotIn("secret-key", (root / "settings.ini").read_text(encoding="utf-8"))
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
            kinds = [kind for kind, _ in calls]
            self.assertLess(kinds.index("search"), kinds.index("inspect"))
            self.assertLess(kinds.index("inspect"), kinds.index("download"))
            window._show_history([{"query": "10.1234/example", "doi": "10.1234/example",
                                   "title": "Example Paper", "status": "downloaded",
                                   "source": "openalex", "updated_at": "2026-10-10", "path": "missing.pdf"}])
            window.history_filter.setText("10.1234/example")
            self.assertFalse(window.history_table.isRowHidden(0))
            self.assertFalse(window.history_open_button.isEnabled())
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_failed_download_does_not_stop_pending_queue(self):
        def fake_perform(task, _config):
            if task.kind == "history":
                return []
            if task.kind == "import":
                return ["10.1234/bad", "10.1234/good"]
            if task.kind == "download":
                time.sleep(0.03)
                if task.query.endswith("bad"):
                    return Result(task.query, "failed", error_code="invalid_pdf", message="HTML response")
                return Result(task.query, "downloaded", doi=task.query, source="openalex")
            raise AssertionError(task.kind)

        with patch("paperget.gui_window.perform", side_effect=fake_perform), \
             patch("paperget.gui_window.BatchPreviewDialog.exec", return_value=1):
            window = MainWindow()
            self.wait_idle(window)
            window._run_task(Task("import", path=Path("fake.txt")))
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

    def test_batch_preview_deduplicates_and_pause_defers_download(self):
        preview = BatchPreviewDialog(["10.1234/A", "10.1234/a", "Different title"], None)
        self.assertEqual(preview.queries, ["10.1234/A", "Different title"])
        preview.deleteLater()
        calls = []

        def fake_perform(task, _config):
            calls.append(task.kind)
            if task.kind == "history":
                return []
            if task.kind == "download":
                return Result(task.query, "downloaded", doi=task.query)
            raise AssertionError(task.kind)

        with patch("paperget.gui_window.perform", side_effect=fake_perform):
            window = MainWindow()
            self.wait_idle(window)
            window._toggle_queue()
            window._enqueue("10.1234/a")
            self.assertEqual(calls, ["history"])
            self.assertEqual(window.queue_table.item(0, 1).text(), "等待")
            window._toggle_queue()
            for _ in range(200):
                self.app.processEvents()
                if window.queue_table.item(0, 1).text() == "已下载":
                    break
                time.sleep(0.01)
            self.assertEqual(window.queue_table.item(0, 1).text(), "已下载")
            self.wait_idle(window)
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_manual_pdf_action_records_queue_result(self):
        def fake_perform(task, _config):
            if task.kind == "history":
                return []
            if task.kind == "attach_pdf":
                return Result(task.query, "downloaded", doi=task.query,
                              path=task.path, source="manual")
            raise AssertionError(task.kind)

        with patch("paperget.gui_window.perform", side_effect=fake_perform), \
             patch("paperget.gui_window.QFileDialog.getOpenFileName", return_value=("C:/picked.pdf", "PDF")):
            window = MainWindow()
            self.wait_idle(window)
            window._attach_pdf("10.1234/example")
            for _ in range(200):
                self.app.processEvents()
                if window.queue_table.item(0, 1).text() == "已下载":
                    break
                time.sleep(0.01)
            self.assertEqual(window.queue_table.item(0, 1).text(), "已下载")
            self.assertEqual(window.queue_table.item(0, 3).text(), str(Path("C:/picked.pdf")))
            self.wait_idle(window)
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
