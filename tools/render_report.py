#!/usr/bin/env python3
"""把 Markdown 验收报告渲染成自包含 HTML（用于截图或打印成 PDF）。

不引第三方库，只处理本项目文档用到的语法：标题、段落、表格、围栏代码块、
有序/无序列表、引用、水平线，以及行内粗体 / 行内代码 / 链接。
用法：python tools/render_report.py ACCEPTANCE_REPORT.md docs/acceptance-report.html
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

BT = chr(96)  # 反引号：避免在本文件里出现三连反引号混淆

CSS = """
body{font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;max-width:980px;margin:0 auto;
     padding:120px 24px 60px;line-height:1.65;color:#1f2328;background:#fff}
h1{font-size:28px;border-bottom:3px solid #0969da;padding-bottom:8px;margin-top:44px}
h1:first-child{margin-top:0}
h2{font-size:21px;margin-top:32px;border-bottom:1px solid #d0d7de;padding-bottom:6px}
h3{font-size:17px;margin-top:24px}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}
th,td{border:1px solid #d0d7de;padding:7px 10px;text-align:left;vertical-align:top}
th{background:#f6f8fa;font-weight:600}
tr:nth-child(even) td{background:#fcfcfd}
code{background:#f6f8fa;padding:2px 5px;border-radius:4px;font-family:Consolas,'Courier New',monospace;font-size:13px}
pre{background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;padding:12px 14px;overflow:auto}
pre code{background:none;padding:0;font-size:12.5px;line-height:1.5}
blockquote{border-left:4px solid #d0d7de;margin:16px 0;padding:2px 16px;color:#57606a;background:#fafbfc}
hr{border:0;border-top:1px solid #d0d7de;margin:32px 0}
ul,ol{padding-left:26px}
li{margin:4px 0}
"""

INLINE_CODE = re.compile(BT + "([^" + BT + "]+)" + BT)
INLINE_BOLD = re.compile(r"\*\*([^*]+)\*\*")
INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline(text: str) -> str:
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append("<code>" + html.escape(match.group(1)) + "</code>")
        return "\x00%d\x00" % (len(spans) - 1)

    text = INLINE_CODE.sub(stash, text)
    text = html.escape(text)
    text = INLINE_BOLD.sub(r"<strong>\1</strong>", text)
    text = INLINE_LINK.sub(r'<a href="\2">\1</a>', text)
    for index, span in enumerate(spans):
        text = text.replace("\x00%d\x00" % index, span)
    return text


def is_table_sep(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= set("|-: ") and "-" in stripped


def convert(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]

        if line.strip().startswith(BT * 3):
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith(BT * 3):
                block.append(lines[index])
                index += 1
            index += 1
            out.append("<pre><code>" + html.escape(chr(10).join(block)) + "</code></pre>")
            continue

        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            level = len(match.group(1))
            out.append(f"<h{level}>{inline(match.group(2))}</h{level}>")
            index += 1
            continue

        if line.strip() in ("---", "***", "___"):
            out.append("<hr>")
            index += 1
            continue

        if line.strip().startswith("|") and index + 1 < len(lines) and is_table_sep(lines[index + 1]):
            header = [cell.strip() for cell in line.strip().strip("|").split("|")]
            index += 2
            body: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                body.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue

        if line.startswith("    ") and line.strip():
            block = []
            while index < len(lines) and (lines[index].startswith("    ") or not lines[index].strip()):
                block.append(lines[index][4:] if lines[index].startswith("    ") else "")
                index += 1
            while block and not block[-1].strip():
                block.pop()
            out.append("<pre><code>" + html.escape(chr(10).join(block)) + "</code></pre>")
            continue

        if line.strip().startswith(">"):
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            out.append("<blockquote>" + inline(" ".join(quote)) + "</blockquote>")
            continue

        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.", line))
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>")
            while index < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[index]):
                item = re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[index])
                out.append("<li>" + inline(item) + "</li>")
                index += 1
            out.append(f"</{tag}>")
            continue

        if not line.strip():
            index += 1
            continue

        paragraph: list[str] = []
        while (index < len(lines) and lines[index].strip()
               and not lines[index].strip().startswith(("#", "|", ">", BT * 3))
               and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[index])):
            paragraph.append(lines[index].strip())
            index += 1
        out.append("<p>" + inline(" ".join(paragraph)) + "</p>")

    return chr(10).join(out)


def main() -> int:
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    body = convert(source.read_text(encoding="utf-8"))
    page = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>" + html.escape(source.stem) + "</title><style>" + CSS + "</style></head><body>"
        + body + "</body></html>"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    print(f"rendered {source} -> {target} ({len(page)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())