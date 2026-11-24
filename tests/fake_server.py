#!/usr/bin/env python3
"""stdlib 桩服务：离线复现 403 / 429 / 500 / 空页 / robots 禁止 / 重复页。

单独运行：python tests/fake_server.py 8000 --scenario 403
被测试导入：httpd, thread, port = serve(0, "403")
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCENARIOS = (
    "ok",           # 3 页正常，第 3 页无 next
    "403",          # 第 2 页 403
    "429",          # 第 2 页 429 + Retry-After: 30
    "500",          # 第 2 页总是 500
    "emptynext",    # 第 2 页 0 条但仍有 next
    "emptyend",     # 第 2 页 0 条且无 next（越界空页，模拟 /page/11/）
    "noquotes",     # 第 1 页 0 条且无 next
    "disallow",     # robots.txt Disallow: /
    "absent",       # robots.txt 404
    "duplicate",    # 第 2 页与第 1 页完全相同
    "missing",      # 第 1 页有一条缺 author
    "loop",         # 第 1 页的 next 指回自己
)


def _quote(text: str, author: str | None, tags: list[str]) -> str:
    tag_html = "".join(f'<a class="tag" href="#">{tag}</a>' for tag in tags)
    author_html = f'<small class="author">{author}</small>' if author else ""
    return (
        '<div class="quote"><span class="text">' + text + "</span>"
        "<span>by " + author_html + "</span>"
        '<div class="tags">' + tag_html + "</div></div>"
    )


def build_page(page: int, total_pages: int, quotes: list[tuple[str, str | None, list[str]]],
               force_next: str | None = None) -> str:
    body = "".join(_quote(*quote) for quote in quotes)
    if force_next:
        next_html = f'<li class="next"><a href="{force_next}">Next</a></li>'
    elif page < total_pages:
        next_html = f'<li class="next"><a href="/page/{page + 1}/">Next</a></li>'
    else:
        next_html = ""
    return (
        "<html><head><title>Quotes to Scrape</title></head><body>"
        f'<div class="header"><h1>Quotes to Scrape</h1></div><div class="container">{body}'
        f'<nav><ul class="pager">{next_html}</ul></nav></div></body></html>'
    )


def default_quotes(page: int) -> list[tuple[str, str | None, list[str]]]:
    return [
        (f'“Quote {page}-{index} for demo, with \u201cquotes\u201d.”', f"Author {index}", ["tag-a", "tag-b"])
        for index in range(1, 11)
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静音，避免污染测试输出
        pass

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8", extra: dict | None = None):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        state = self.server.state
        path = self.path.split("?")[0]
        state["log"].append({"path": path, "ua": self.headers.get("User-Agent", ""), "ts": time.time()})

        if path == "/_log":
            self._send(200, json.dumps(state["log"]), "application/json")
            return

        if path == "/robots.txt":
            if state["scenario"] == "absent":
                self._send(404, "not found", "text/plain")
            elif state["scenario"] == "disallow":
                self._send(200, "User-agent: *\nDisallow: /\n", "text/plain")
            else:
                self._send(200, "User-agent: *\nAllow: /\n", "text/plain")
            return

        match = re.match(r"^/page/(\d+)/?$", path)
        page = 1 if path in ("/", "") else int(match.group(1)) if match else 0
        if page == 0:
            self._send(404, "not found", "text/plain")
            return

        scenario = state["scenario"]
        total_pages = 3

        # 异常场景：第 2 页出问题
        if page == 2 and scenario == "403":
            self._send(403, "<h1>403 Forbidden</h1>")
            return
        if page == 2 and scenario == "429":
            self._send(429, "<h1>429 Too Many Requests</h1>", extra={"Retry-After": "30"})
            return
        if page == 2 and scenario == "500":
            self._send(500, "<h1>500 Internal Server Error</h1>")
            return

        if scenario == "emptynext" and page == 2:
            self._send(200, build_page(2, total_pages, [], force_next="/page/3/"))
            return
        if scenario == "emptyend" and page == 2:
            self._send(200, build_page(2, 2, []))
            return
        if scenario == "noquotes" and page == 1:
            self._send(200, build_page(1, 1, []))
            return
        if scenario == "missing" and page == 1:
            quotes = default_quotes(1)
            quotes[3] = (quotes[3][0], None, quotes[3][2])  # 第 4 条缺 author
            self._send(200, build_page(1, 1, quotes))
            return
        if scenario == "loop" and page == 1:
            self._send(200, build_page(1, 1, default_quotes(1), force_next="/page/1/"))
            return
        if scenario == "duplicate":
            # 第 1、2 页内容完全相同
            self._send(200, build_page(page, total_pages, default_quotes(1)))
            return

        self._send(200, build_page(page, total_pages, default_quotes(page)))


def serve(port: int = 0, scenario: str = "ok") -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.state = {"scenario": scenario, "log": []}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, httpd.server_address[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="离线桩服务")
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--scenario", default="ok", choices=SCENARIOS)
    args = parser.parse_args()
    httpd, _thread, port = serve(args.port, args.scenario)
    print(f"fake_server listening on http://127.0.0.1:{port}/ scenario={args.scenario}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
