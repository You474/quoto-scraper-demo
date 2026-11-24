#!/usr/bin/env python3
"""校验一次运行的导出结果（配合 ACCEPTANCE_REPORT 使用）。

用法：python tests/verify_output.py out\quotes_20261124_081908.csv out\quotes_20261124_081908.json
退出码 0 = 全部通过，1 = 有失败项。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def main() -> int:
    csv_path = Path(sys.argv[1])
    json_path = Path(sys.argv[2])
    checks: list[tuple[str, bool, str]] = []

    raw = csv_path.read_bytes()
    checks.append(("CSV 以 utf-8-sig BOM 开头", raw[:3] == b"\xef\xbb\xbf", raw[:3].hex()))

    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header, data = rows[0], rows[1:]
    checks.append(("CSV 表头固定", header == ["quote_id", "text", "author", "tags", "page"], str(header)))
    checks.append(("CSV 数据行 = 100", len(data) == 100, str(len(data))))

    records = json.loads(json_path.read_text(encoding="utf-8"))
    checks.append(("JSON 是数组且 100 条", isinstance(records, list) and len(records) == 100, str(len(records))))
    checks.append(("JSON 每元素 5 个键", all(set(r) == {"quote_id", "text", "author", "tags", "page"} for r in records), "-"))
    checks.append(("quote_id 唯一", len({r["quote_id"] for r in records}) == len(records), "-"))
    checks.append(("text/author 全部非空", all(r["text"].strip() and r["author"].strip() for r in records), "-"))
    pages = sorted({r["page"] for r in records})
    checks.append(("页码覆盖 1..10", pages == list(range(1, 11)), str(pages)))
    checks.append(("每页 10 条", all(sum(1 for r in records if r["page"] == p) == 10 for p in pages), "-"))
    checks.append(("无 HTML 残留", all("<" not in r["text"] for r in records), "-"))
    checks.append(("弯引号保留", records[0]["text"].startswith("\u201c"), records[0]["text"][:12]))
    checks.append(("André 未被破坏", any("Andr\u00e9 Gide" == r["author"] for r in records), "-"))
    checks.append(("tags 为 list", all(isinstance(r["tags"], list) for r in records), "-"))
    checks.append(("CSV 行数与 JSON 一致", len(data) == len(records), f"{len(data)} vs {len(records)}"))
    checks.append(("CSV 第 1 行与 JSON[0] 一致", data[0][0] == records[0]["quote_id"], data[0][0]))
    checks.append(("无 .tmp 残留", not list(csv_path.parent.glob("*.tmp")), "-"))

    failed = [name for name, ok, _ in checks if not ok]
    for name, ok, detail in checks:
        print(("PASS  " if ok else "FAIL  ") + name + ("  (" + detail + ")" if detail != "-" else ""))
    print(f"\n{len(checks) - len(failed)}/{len(checks)} 通过")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
