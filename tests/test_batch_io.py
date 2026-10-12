import json
import tempfile
import unittest
from pathlib import Path

from paperget.batch_io import read_batch_preview, read_queries, write_report


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

    def test_gui_preview_reports_invalid_row_numbers_without_changing_cli_reader(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            path = Path(directory) / "papers.csv"
            path.write_text('doi_or_title\n10.1234/ok\n""\n10.bad/doi\nhttps://example.org/page\n中文论文标题\n',
                            encoding="utf-8")
            preview = read_batch_preview(path)
            self.assertEqual(preview.queries, ["10.1234/ok", "中文论文标题"])
            self.assertEqual(preview.invalid_rows, [
                (3, "空值或无标题文字"),
                (4, "DOI 格式不完整"),
                (5, "链接中没有 DOI"),
            ])
            self.assertIn("10.bad/doi", read_queries(path))


if __name__ == "__main__":
    unittest.main()
