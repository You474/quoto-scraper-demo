#!/usr/bin/env python3
"""端到端验收：起 stdlib 桩服务，跑 scraper.py，断言退出码/请求序列/文件内容。

对应 acceptance.md 的 AC-04/05/11/13/14/15/16/17/18/19/22/23/24 与 stop 规则 S9。
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_server  # noqa: E402


def run_scenario(scenario: str, max_pages: str = "3", *extra: str):
    """在随机端口起桩服务 -> 跑 scraper -> 返回 (proc, files, contents, request_log)。"""
    httpd, _thread, port = fake_server.serve(0, scenario)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    "scraper.py",
                    "--base-url",
                    f"http://127.0.0.1:{port}/",
                    "--delay",
                    "0.2",
                    "--out-dir",
                    tmp,
                    "--max-pages",
                    max_pages,
                    *extra,
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            files = {p.name: p for p in Path(tmp).glob("*")}
            contents = {}
            for name, path in files.items():
                encoding = "utf-8-sig" if name.endswith(".csv") else "utf-8"
                contents[name] = path.read_text(encoding=encoding)
            return proc, files, contents, list(httpd.state["log"])
    finally:
        httpd.shutdown()


def csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def errors_of(contents: dict) -> list[dict]:
    for name, text in contents.items():
        if name.endswith(".jsonl"):
            return [json.loads(line) for line in text.splitlines() if line.strip()]
    return []


def quotes_json(contents: dict) -> list[dict]:
    for name, text in contents.items():
        if name.endswith(".json"):
            return json.loads(text)
    return []


class TestHappyPath(unittest.TestCase):
    def test_three_pages(self):
        proc, files, contents, log = run_scenario("ok")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("pages=3", proc.stderr)
        self.assertIn("rows_kept=30", proc.stderr)
        self.assertIn("dup=0", proc.stderr)
        self.assertIn("robots=present", proc.stderr)  # ok 场景 robots.txt 存在且 Allow
        rows = csv_rows([t for n, t in contents.items() if n.endswith(".csv")][0])
        self.assertEqual(rows[0], ["quote_id", "text", "author", "tags", "page"])
        self.assertEqual(len(rows) - 1, 30)          # AC-18：表头 + 30 行
        self.assertEqual(len(quotes_json(contents)), 30)  # AC-19
        self.assertEqual(rows[1][4], "1")            # page 列

    def test_author_column_is_not_a_dedup_key(self):
        """同一 author 不同 text 必须都保留（AC-12 的离线版）。"""
        proc, _files, contents, _log = run_scenario("ok", "1")
        rows = quotes_json(contents)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len({r["quote_id"] for r in rows}), len(rows))


class TestStopOnForbidden(unittest.TestCase):
    def test_403_stops_immediately(self):
        proc, files, contents, log = run_scenario("403", "5")
        paths = [entry["path"] for entry in log]
        self.assertEqual(proc.returncode, 2, proc.stderr)      # AC-13
        self.assertIn("/page/2/", paths)
        self.assertNotIn("/page/3/", paths)                    # 不继续翻页
        self.assertEqual(paths.count("/page/2/"), 1)           # 不重试
        events = errors_of(contents)
        self.assertTrue(any(e["status"] == 403 and e["reason"] == "http_forbidden" for e in events))
        csv_files = [n for n in files if n.endswith(".csv")]
        self.assertEqual(len(csv_files), 1)                     # 已采第 1 页仍落盘
        self.assertEqual(len(csv_rows(contents[csv_files[0]])) - 1, 10)

    def test_429_stops_and_records_retry_after(self):
        proc, files, contents, log = run_scenario("429", "5")
        paths = [entry["path"] for entry in log]
        self.assertEqual(proc.returncode, 2, proc.stderr)      # AC-14
        self.assertEqual(paths.count("/page/2/"), 1)           # 只有 1 次，没有换身份重试
        self.assertNotIn("/page/3/", paths)
        events = errors_of(contents)
        hit = [e for e in events if e["reason"] == "http_rate_limited"]
        self.assertEqual(len(hit), 1)
        self.assertIn("retry_after=30", hit[0]["detail"])
        self.assertEqual(len([n for n in files if n.endswith(".csv")]), 1)


class TestRetryOnServerError(unittest.TestCase):
    def test_500_retries_twice_then_stops(self):
        proc, _files, contents, log = run_scenario("500", "5")
        paths = [entry["path"] for entry in log]
        self.assertEqual(proc.returncode, 2, proc.stderr)      # AC-15
        self.assertEqual(paths.count("/page/2/"), 3)           # 1 次 + 2 次重试
        attempts = [e for e in errors_of(contents) if e["reason"] == "http_server_error"]
        self.assertEqual(len(attempts), 3)


class TestParseProblems(unittest.TestCase):
    def test_missing_author_row_is_skipped(self):
        proc, files, contents, _log = run_scenario("missing", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)      # AC-16
        self.assertIn("parse_skips=1", proc.stderr)
        rows = csv_rows([t for n, t in contents.items() if n.endswith(".csv")][0])
        self.assertEqual(len(rows) - 1, 9)

    def test_empty_page_with_next_is_an_error(self):
        proc, files, contents, _log = run_scenario("emptynext", "3")
        self.assertEqual(proc.returncode, 2, proc.stderr)      # AC-17
        reasons = [e["reason"] for e in errors_of(contents)]
        self.assertIn("parse_empty_page_with_next", reasons)
        # 已采的第 1 页数据照常落盘，但绝不能只有表头的空 CSV
        csv_files = [n for n in files if n.endswith(".csv")]
        self.assertEqual(len(csv_files), 1)
        self.assertEqual(len(csv_rows(contents[csv_files[0]])) - 1, 10)

    def test_empty_last_page_is_normal_end(self):
        """AC-05：越界页 200 但 0 条且无 next -> 已采数据正常收尾，退出码 0。"""
        proc, files, contents, _log = run_scenario("emptyend", "3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("stop=empty_page", proc.stderr)
        self.assertIn("empty_page", [e["reason"] for e in errors_of(contents)])
        csv_files = [n for n in files if n.endswith(".csv")]
        self.assertEqual(len(csv_files), 1)
        self.assertEqual(len(csv_rows(contents[csv_files[0]])) - 1, 10)

    def test_zero_rows_produces_no_output_files(self):
        proc, files, contents, _log = run_scenario("noquotes", "1")
        self.assertEqual(proc.returncode, 2, proc.stderr)      # AC-05 的另一半
        self.assertIn("no_rows", [e["reason"] for e in errors_of(contents)])
        self.assertEqual([n for n in files if n.endswith((".csv", ".json"))], [])

    def test_pagination_loop_detected(self):
        proc, _files, contents, log = run_scenario("loop", "3")
        self.assertEqual(proc.returncode, 2, proc.stderr)      # S9
        self.assertIn("pagination_loop", [e["reason"] for e in errors_of(contents)])
        self.assertEqual([e["path"] for e in log].count("/page/1/"), 1)


class TestDedup(unittest.TestCase):
    def test_identical_pages_collapse(self):
        proc, _files, contents, _log = run_scenario("duplicate", "2")
        self.assertEqual(proc.returncode, 0, proc.stderr)      # AC-11
        self.assertIn("rows_seen=20", proc.stderr)
        self.assertIn("rows_kept=10", proc.stderr)
        self.assertIn("dup=10", proc.stderr)
        self.assertEqual(len(quotes_json(contents)), 10)
        pages = {row["page"] for row in quotes_json(contents)}
        self.assertEqual(pages, {1})                            # 保留首次出现（第 1 页）


class TestRobots(unittest.TestCase):
    def test_disallow_blocks_everything(self):
        proc, files, contents, log = run_scenario("disallow", "3")
        self.assertEqual(proc.returncode, 1, proc.stderr)      # AC-23
        self.assertEqual([e["path"] for e in log], ["/robots.txt"])   # 零页面请求
        self.assertEqual([n for n in files if n.endswith((".csv", ".json"))], [])
        self.assertIn("robots_disallow", [e["reason"] for e in errors_of(contents)])

    def test_absent_robots_is_recorded_and_continues(self):
        proc, _files, _contents, log = run_scenario("absent", "2")
        self.assertEqual(proc.returncode, 0, proc.stderr)      # AC-22
        self.assertIn("robots=absent", proc.stderr)
        self.assertIn("/page/2/", [e["path"] for e in log])

    def test_user_agent_and_interval(self):
        proc, _files, _contents, log = run_scenario("ok", "3")
        page_hits = [e for e in log if not e["path"].startswith("/robots")]
        self.assertTrue(all("quote-scraper-demo" in e["ua"] for e in page_hits))   # AC-24
        gaps = [b["ts"] - a["ts"] for a, b in zip(page_hits, page_hits[1:])]
        self.assertTrue(gaps and all(gap >= 0.15 for gap in gaps), gaps)
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
