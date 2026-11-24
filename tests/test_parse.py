#!/usr/bin/env python3
"""离线单测：解析、清洗、导出转义、原子写。不打网络。"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import export  # noqa: E402
import scraper  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestClean(unittest.TestCase):
    def test_collapses_inner_whitespace(self):
        self.assertEqual(scraper.clean("  a   b\t\n c  "), "a b c")

    def test_nbsp_is_whitespace(self):
        self.assertEqual(scraper.clean("a\xa0b"), "a b")

    def test_none_and_empty(self):
        self.assertEqual(scraper.clean(None), "")
        self.assertEqual(scraper.clean("   "), "")


class TestQuoteId(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(scraper.make_quote_id("A", "B"), scraper.make_quote_id("A", "B"))

    def test_author_matters(self):
        self.assertNotEqual(scraper.make_quote_id("A", "B"), scraper.make_quote_id("C", "B"))

    def test_format(self):
        self.assertTrue(re.fullmatch(r"[0-9a-f]{12}", scraper.make_quote_id("A", "B")))


class TestParseFixture(unittest.TestCase):
    def test_page1(self):
        html = (FIXTURES / "page1.html").read_text(encoding="utf-8")
        rows, problems, next_href = scraper.parse_page(html, 1)
        self.assertEqual(problems, [])
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["author"], "Albert Einstein")
        self.assertEqual(rows[0]["tags"], ["change", "deep-thoughts", "thinking", "world"])
        self.assertTrue(rows[0]["text"].startswith("\u201c"))
        self.assertTrue(rows[0]["text"].endswith("\u201d"))
        self.assertEqual(next_href, "/page/2/")

    def test_last_page_has_no_next(self):
        html = (FIXTURES / "page10.html").read_text(encoding="utf-8")
        rows, _problems, next_href = scraper.parse_page(html, 10)
        self.assertEqual(len(rows), 10)
        self.assertIsNone(next_href)

    def test_missing_author_is_skipped_not_fatal(self):
        html = (
            '<div class="quote"><span class="text">good</span><small class="author">Me</small></div>'
            '<div class="quote"><span class="text">no author</span></div>'
        )
        rows, problems, next_href = scraper.parse_page(html, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["reason"], "parse_missing_field")
        self.assertIsNone(next_href)

    def test_tags_lowercased_deduped_ordered(self):
        html = (
            '<div class="quote"><span class="text">t</span><small class="author">a</small>'
            '<div class="tags"><a class="tag">Zeta</a><a class="tag">alpha</a><a class="tag">zeta</a></div></div>'
        )
        rows, _problems, _next = scraper.parse_page(html, 1)
        self.assertEqual(rows[0]["tags"], ["zeta", "alpha"])

    def test_page_number_is_recorded(self):
        html = (FIXTURES / "page10.html").read_text(encoding="utf-8")
        rows, _p, _n = scraper.parse_page(html, 10)
        self.assertTrue(all(row["page"] == 10 for row in rows))


class TestCsvEscaping(unittest.TestCase):
    def test_formula_prefixes_are_neutralised(self):
        for raw in ("=SUM(A1)", "+1", "-1", "@cmd", "\tTAB", "\rCR"):
            self.assertEqual(export.escape_csv_cell(raw), "'" + raw, raw)

    def test_plain_text_untouched(self):
        for raw in ("normal", "\u201cquoted\u201d", "123", ""):
            self.assertEqual(export.escape_csv_cell(raw), raw)

    def test_escaping_only_at_export_layer(self):
        """采集/解析层不碰数据：parse 出来的 text 原样，escape 只发生在导出。"""
        html = '<div class="quote"><span class="text">=1+1</span><small class="author">A</small></div>'
        rows, _p, _n = scraper.parse_page(html, 1)
        self.assertEqual(rows[0]["text"], "=1+1")
        self.assertEqual(export.escape_csv_cell(rows[0]["text"]), "'=1+1")

    def test_csv_roundtrip_with_comma_and_quote(self):
        rows = [{"quote_id": "abc123", "text": 'a, b "c"', "author": "Andr\u00e9 Gide", "tags": ["x", "y"], "page": 1}]
        text = export.rows_to_csv_text(rows)
        parsed = list(csv.reader(io.StringIO(text)))
        self.assertEqual(parsed[0], export.CSV_HEADER)
        self.assertEqual(parsed[1][1], 'a, b "c"')
        self.assertEqual(parsed[1][2], "Andr\u00e9 Gide")
        self.assertEqual(parsed[1][3], "x|y")

    def test_empty_tags_become_empty_field(self):
        rows = [{"quote_id": "abc123", "text": "t", "author": "a", "tags": [], "page": 1}]
        parsed = list(csv.reader(io.StringIO(export.rows_to_csv_text(rows))))
        self.assertEqual(parsed[1][3], "")


class TestFiles(unittest.TestCase):
    def test_csv_has_bom_for_excel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.csv"
            export.write_csv([{"quote_id": "a", "text": "t", "author": "b", "tags": [], "page": 1}], path)
            self.assertEqual(path.read_bytes()[:3], b"\xef\xbb\xbf")

    def test_json_roundtrip_keeps_unicode(self):
        rows = [{"quote_id": "a", "text": "\u201cx\u201d", "author": "Andr\u00e9 Gide", "tags": [], "page": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.json"
            export.write_json(rows, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), rows)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.csv"
            export.write_csv([], path)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["q.csv"])

    def test_same_second_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = export.unique_output_path(Path(tmp), "quotes", ".csv", "20261124_080500")
            first.write_text("x", encoding="utf-8")
            second = export.unique_output_path(Path(tmp), "quotes", ".csv", "20261124_080500")
            self.assertEqual(second.name, "quotes_20261124_080500-1.csv")

    def test_errors_jsonl_one_line_per_event(self):
        events = [{"ts": "t", "page": 1, "url": "u", "status": 403, "reason": "http_forbidden", "detail": "d"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.jsonl"
            export.write_errors(events, path)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["reason"], "http_forbidden")


if __name__ == "__main__":
    unittest.main(verbosity=2)
