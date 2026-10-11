import csv
import tempfile
import unittest
from pathlib import Path

from paperget.config import Config
from paperget.gui_backend import Task, perform
from paperget.store import Store


class GuiBackendTests(unittest.TestCase):
    def test_existing_database_gains_diagnostics_table(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            database = Path(directory) / "paperget.sqlite3"
            with Store(database) as store:
                store.connection.execute("DROP TABLE source_events")
                store.connection.commit()
            with Store(database) as store:
                self.assertEqual(store.diagnostics(), [])

    def test_diagnostics_can_be_filtered_and_exported(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            with Store(root / "paperget.sqlite3") as store:
                store.record_source_event("run-1", "10.1234/a", "10.1234/a", "openalex",
                                          "discovery", "empty", error_code="no_open_pdf",
                                          message="No open PDF", host="api.openalex.org")
                store.record_source_event("run-2", "10.1234/b", "10.1234/b", "scihub",
                                          "discovery", "empty", error_code="no_pdf_link")
            config = Config(output_dir=root)
            rows = perform(Task("diagnostics", query="10.1234/a"), config)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["error_code"], "no_open_pdf")
            report = root / "diagnostics.csv"
            perform(Task("export_diagnostics", path=report, format="csv"), config)
            with report.open(encoding="utf-8-sig", newline="") as stream:
                exported = list(csv.DictReader(stream))
            self.assertEqual(len(exported), 2)
            self.assertEqual({row["source"] for row in exported}, {"openalex", "scihub"})


if __name__ == "__main__":
    unittest.main()
