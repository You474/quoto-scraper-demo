#!/usr/bin/env python3
"""公开数据采集脚本（Demo：quotes.toscrape.com）。

M2 范围：顺序翻页、行级去重、CSV/JSON 导出、robots 检查、异常与停止策略。
合规：只采公开页面，串行限速，403/429 立即停止，不登录、不绕验证码。
规则出处：spec.md §4/§5/§6/§8，验收：acceptance.md。
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import export as exporter

DEFAULT_BASE_URL = "https://quotes.toscrape.com/"
USER_AGENT = "quote-scraper-demo/0.1 (+educational demo)"
TIMEOUT_SECONDS = 10
MIN_DELAY = 0.2          # 不接受 delay=0（spec §12）
DEFAULT_DELAY = 1.0
JITTER_SECONDS = 0.3
RETRY_BACKOFF = (2, 4)   # 5xx / 网络错误：重试 2 次

EXIT_OK = 0
EXIT_PRECONDITION = 1
EXIT_PARTIAL = 2


def clean(value: str | None) -> str:
    """去首尾空白，内部连续空白（含 \xa0）折叠为单空格。"""
    return " ".join((value or "").split())


def make_quote_id(author: str, text: str) -> str:
    raw = f"{author}\x1f{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event(page: int | None, url: str, status: int | None, reason: str, detail: str = "") -> dict:
    return {"ts": now_iso(), "page": page, "url": url, "status": status, "reason": reason, "detail": detail}


def parse_page(html: str, page: int) -> tuple[list[dict], list[dict], str | None]:
    """解析一页 -> (行, 问题, 下一页绝对地址或 None)。单条缺字段只跳过该条。"""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    problems: list[dict] = []

    for index, block in enumerate(soup.select("div.quote"), start=1):
        text_el = block.select_one("span.text")
        author_el = block.select_one("small.author")
        text = clean(text_el.get_text() if text_el else "")
        author = clean(author_el.get_text() if author_el else "")
        if not text or not author:
            problems.append(
                event(page, "", None, "parse_missing_field", f"index={index} text={bool(text)} author={bool(author)}")
            )
            continue
        tags = [clean(tag.get_text()).lower() for tag in block.select("a.tag")]
        tags = list(dict.fromkeys(tag for tag in tags if tag))
        rows.append(
            {
                "quote_id": make_quote_id(author, text),
                "text": text,
                "author": author,
                "tags": tags,
                "page": page,
            }
        )

    next_el = soup.select_one("li.next a")
    next_href = next_el["href"] if next_el and next_el.get("href") else None
    return rows, problems, next_href


def load_robots(session: requests.Session, base_url: str, errors: list[dict]) -> tuple[str, RobotFileParser | None]:
    """返回 (状态, 解析器)。状态：present / absent / unknown。"""
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        response = session.get(robots_url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        errors.append(event(None, robots_url, None, "robots_unknown", str(exc)))
        return "unknown", None

    if response.status_code in (404, 410):
        return "absent", None
    if response.status_code != 200:
        errors.append(event(None, robots_url, response.status_code, "robots_unknown", "非 200/404"))
        return "unknown", None

    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return "present", parser


def fetch(session: requests.Session, url: str, page: int, errors: list[dict]) -> requests.Response | None:
    """单次请求 + 对 5xx/网络错误重试 2 次（退避 2s、4s）。403/429 不重试，原样返回。"""
    attempts = len(RETRY_BACKOFF) + 1
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
        except requests.Timeout as exc:
            errors.append(event(page, url, None, "timeout", f"attempt={attempt + 1} {exc}"))
        except requests.RequestException as exc:
            errors.append(event(page, url, None, "network_error", f"attempt={attempt + 1} {exc}"))
        else:
            if response.status_code < 500:
                return response
            errors.append(event(page, url, response.status_code, "http_server_error", f"attempt={attempt + 1}"))
        if attempt < len(RETRY_BACKOFF):
            time.sleep(RETRY_BACKOFF[attempt])
    return None


def crawl(session: requests.Session, base_url: str, max_pages: int, delay: float,
          errors: list[dict], stats: dict) -> tuple[list[dict], str]:
    rows: list[dict] = []
    seen: set[str] = set()
    visited: set[str] = set()
    url = base_url
    stop_reason = "max_pages"

    while stats["pages"] < max_pages:
        if url in visited:
            errors.append(event(stats["pages"] + 1, url, None, "pagination_loop", "下一跳 URL 已访问"))
            stop_reason = "pagination_loop"
            break
        visited.add(url)
        stats["pages"] += 1
        page_no = stats["pages"]

        response = fetch(session, url, page_no, errors)
        if response is None:
            stop_reason = "fetch_failed"
            break

        status = response.status_code
        if status == 403:
            errors.append(event(page_no, url, 403, "http_forbidden", "403 立即停止，不重试"))
            stop_reason = "http_forbidden"
            break
        if status == 429:
            retry_after = response.headers.get("Retry-After", "")
            errors.append(event(page_no, url, 429, "http_rate_limited", f"retry_after={retry_after} 立即停止"))
            stop_reason = "http_rate_limited"
            break
        if status != 200:
            errors.append(event(page_no, url, status, "http_error", "非 200 响应"))
            stop_reason = "http_error"
            break

        page_rows, problems, next_href = parse_page(response.text, page_no)
        errors.extend(problems)
        stats["rows_seen"] += len(page_rows)

        for row in page_rows:
            if row["quote_id"] in seen:
                stats["rows_duplicated"] += 1
                continue
            seen.add(row["quote_id"])
            rows.append(row)

        next_url = urljoin(response.url, next_href) if next_href else None

        if not page_rows:
            if next_url:
                errors.append(event(page_no, url, status, "parse_empty_page_with_next", "有 next 但 0 条，选择器可能失效"))
                stop_reason = "parse_empty_page_with_next"
                break
            if rows:
                errors.append(event(page_no, url, status, "empty_page", "越界空页，按正常收尾"))
                stop_reason = "empty_page"
                break
            stop_reason = "no_rows"
            break

        if not next_url:
            stop_reason = "no_next"
            break

        url = next_url
        time.sleep(delay + random.uniform(0, JITTER_SECONDS))

    return rows, stop_reason


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="采集 quotes.toscrape.com 公开数据（demo）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="相邻请求间隔秒，最小 0.2")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--format", choices=("both", "csv", "json"), default="both")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    if args.max_pages < 1:
        print("[error] --max-pages 必须 >= 1", file=sys.stderr)
        return EXIT_PRECONDITION
    if args.delay < MIN_DELAY:
        print(f"[error] --delay 不能小于 {MIN_DELAY}（不做高频请求）", file=sys.stderr)
        return EXIT_PRECONDITION
    if not args.base_url.startswith(("http://", "https://")):
        print("[error] --base-url 必须以 http:// 或 https:// 开头", file=sys.stderr)
        return EXIT_PRECONDITION

    base_url = args.base_url.rstrip("/") + "/"
    out_dir = Path(args.out_dir)
    errors: list[dict] = []
    stats = {"pages": 0, "rows_seen": 0, "rows_kept": 0, "rows_duplicated": 0, "parse_skips": 0}
    started = time.time()

    session = requests.Session()
    robots_state, robots_parser = load_robots(session, base_url, errors)

    if robots_state == "present" and robots_parser is not None and not robots_parser.can_fetch(USER_AGENT, base_url):
        errors.append(event(None, urljoin(base_url, "robots.txt"), 200, "robots_disallow", "robots.txt 禁止抓取"))
        try:
            exporter.write_errors(errors, exporter.unique_output_path(out_dir, "errors", ".jsonl", time.strftime("%Y%m%d_%H%M%S")))
        except OSError:
            pass
        print(f"[error] robots.txt 禁止抓取 {base_url}，未发起任何页面请求", file=sys.stderr)
        return EXIT_PRECONDITION

    effective_delay = max(args.delay, MIN_DELAY)
    if robots_state == "unknown":
        effective_delay = max(effective_delay, 2.0)
        print("[warn] robots.txt 无法确认，已把间隔提升到 2s", file=sys.stderr)

    rows, stop_reason = crawl(session, base_url, args.max_pages, effective_delay, errors, stats)
    stats["rows_kept"] = len(rows)
    stats["parse_skips"] = sum(1 for e in errors if e["reason"] == "parse_missing_field")
    elapsed = time.time() - started
    stamp = time.strftime("%Y%m%d_%H%M%S")

    csv_path = json_path = None
    try:
        if not rows:
            errors.append(event(None, base_url, None, "no_rows", "一条都没采到，不产出空文件"))
        else:
            if args.format in ("both", "csv"):
                csv_path = exporter.write_csv(rows, exporter.unique_output_path(out_dir, "quotes", ".csv", stamp))
            if args.format in ("both", "json"):
                json_path = exporter.write_json(rows, exporter.unique_output_path(out_dir, "quotes", ".json", stamp))
        errors_path = exporter.write_errors(errors, exporter.unique_output_path(out_dir, "errors", ".jsonl", stamp))
    except OSError as exc:
        print(f"[error] 写入失败: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    normal_end = {"no_next", "max_pages", "empty_page"}
    exit_code = EXIT_OK if stop_reason in normal_end and rows else EXIT_PARTIAL

    print(
        f"pages={stats['pages']} rows_seen={stats['rows_seen']} rows_kept={stats['rows_kept']} "
        f"dup={stats['rows_duplicated']} parse_skips={stats['parse_skips']} errors={len(errors)} "
        f"robots={robots_state} stop={stop_reason} elapsed={elapsed:.1f}s",
        file=sys.stderr,
    )
    if csv_path:
        print(f"csv={csv_path}", file=sys.stderr)
    if json_path:
        print(f"json={json_path}", file=sys.stderr)
    print(f"errors_log={errors_path}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
