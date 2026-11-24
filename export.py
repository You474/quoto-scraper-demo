#!/usr/bin/env python3
"""导出层：CSV / JSON / JSONL 写入。

设计约束（spec §7）：
- 采集与解析层绝不修改数据；CSV 公式注入（CWE-1236）的转义只发生在这里。
- 原子写：先写 .tmp 再 os.replace，进程被杀也不会留下半截文件。
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

CSV_HEADER = ["quote_id", "text", "author", "tags", "page"]

# Excel 会把以这些字符开头的单元格当公式执行
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_csv_cell(value: str) -> str:
    """CWE-1236 防护：仅在 CSV 导出时加前导单引号，JSON 与内存数据保持原样。"""
    if value and value[0] in FORMULA_PREFIXES:
        return "'" + value
    return value


def _atomic_write_text(path: Path, data: str, encoding: str, newline: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline=newline) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return path


def rows_to_csv_text(rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            [
                escape_csv_cell(str(row.get("quote_id", ""))),
                escape_csv_cell(str(row.get("text", ""))),
                escape_csv_cell(str(row.get("author", ""))),
                "|".join(row.get("tags", []) or []),
                row.get("page", ""),
            ]
        )
    return buffer.getvalue()


def write_csv(rows: list[dict], path: Path) -> Path:
    """utf-8-sig：Excel 双击直开不乱码。"""
    return _atomic_write_text(path, rows_to_csv_text(rows), encoding="utf-8-sig", newline="")


def write_json(rows: list[dict], path: Path) -> Path:
    data = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    return _atomic_write_text(path, data, encoding="utf-8")


def write_errors(events: list[dict], path: Path) -> Path:
    """JSONL：一行一个事件；无事件时写空文件。"""
    data = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    return _atomic_write_text(path, data, encoding="utf-8")


def unique_output_path(out_dir: Path, stem: str, suffix: str, stamp: str) -> Path:
    """同秒重跑不覆盖：quotes_20261124_080500.csv -> ...-1.csv。"""
    out_dir = Path(out_dir)
    candidate = out_dir / f"{stem}_{stamp}{suffix}"
    index = 1
    while candidate.exists():
        candidate = out_dir / f"{stem}_{stamp}-{index}{suffix}"
        index += 1
    return candidate
