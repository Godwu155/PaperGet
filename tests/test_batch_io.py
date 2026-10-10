import json
import tempfile
import unittest
from pathlib import Path

from paperget.batch_io import read_queries, write_report


class BatchIoTests(unittest.TestCase):
    def test_utf8_bom_csv_and_txt_share_cli_gui_semantics(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            csv_file = root / "papers.csv"
            csv_file.write_text("doi_or_title,note\n10.1234/a,一\n,skip\n Title words ,二\n", encoding="utf-8-sig")
            self.assertEqual(read_queries(csv_file), ["10.1234/a", "Title words"])
            txt_file = root / "papers.txt"
            txt_file.write_text("\ufeff# comment\n10.1234/b\n\n Title words \n", encoding="utf-8")
            self.assertEqual(read_queries(txt_file), ["10.1234/b", "Title words"])

    def test_reports_preserve_unicode_and_cli_fields(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            rows = [{"query": "中文标题", "status": "failed", "error_code": "no_pdf", "extra": 1}]
            write_report(root / "report.json", rows, "json")
            write_report(root / "report.csv", rows, "csv")
            self.assertEqual(json.loads((root / "report.json").read_text(encoding="utf-8")), rows)
            self.assertIn("中文标题", (root / "report.csv").read_text(encoding="utf-8-sig"))
            with self.assertRaises(ValueError):
                write_report(root / "report.txt", rows, "txt")


if __name__ == "__main__":
    unittest.main()
