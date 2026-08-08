# -*- coding: utf-8 -*-
"""Markdown 表格 → CSV 转换小工具（输出策略：宽松兼容 Excel）。

读入 .md 文件，把其中的 GFM 表格逐张提取出来，输出为同名 .csv
（第一张表 → foo.csv，后续表 → foo_2.csv、foo_3.csv……）。

输出策略（玩家抉择：策略B 宽松兼容Excel）：
- 字段含逗号或引号时用双引号包裹，字段内引号翻倍（""），符合 Excel 习惯；
- 单元格内的换行/`<br>` 一律压平为空格（多行单元格丢失原文结构，换取 Excel 双击直开不乱行）；
- 行尾统一 CRLF；
- 列数以表头为准：行内列不足补空串、超出截断，绝不抛错；
- HTML 标签等怪数据只做降级清洗，任何清洗异常都原样保留原文。

用法：
    python galgame_coding/scratch/md2csv.py 文件.md
    python -m galgame_coding.scratch.md2csv 文件.md
"""

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 解析层

_SPLIT_ROW = re.compile(r"^\s*\|?\s*:?-{3,}\s*:?\s*(\|\s*:?-{3,}\s*:?\s*)*\|?\s*$")
_CELL_ESCAPE = re.compile(r"\\([\\|`*_{}\[\]()#+\-.!>])")  # GFM 常见转义
_HTML_TAG = re.compile(r"<[^>\n]*>")                        # HTML 标签（含 <br>）
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")                  # 以 | 开头且结尾的行


def _is_separator_row(line: str) -> bool:
    """判断是否为表格分隔行（| --- | :---: | 等）。"""
    stripped = line.strip().strip("|")
    cells = stripped.split("|")
    return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}\s*:?\s*", c) for c in cells)


def _split_cells(line: str) -> list[str]:
    """按未转义的 | 拆分单元格，返回去除首尾空白后的列表。"""
    # 用占位符保护 \| 转义竖线，再按 | 拆分
    protected = _CELL_ESCAPE.sub(lambda m: f"\x00{ord(m.group(1)):02x}", line)
    raw = protected.strip().strip("|").split("|")
    out = []
    for cell in raw:
        # 还原转义竖线
        cell = re.sub(r"\x00([0-9a-f]{2})", lambda m: chr(int(m.group(1), 16)), cell)
        out.append(cell.strip())
    return out


def extract_tables(text: str) -> list[list[list[str]]]:
    """从 Markdown 文本中提取所有 GFM 表格。

    返回 [[[单元格, ...], ...], ...]：外层每张表，中层每行，内层单元格。
    只认「表头行 + 分隔行 + 数据行」的完整结构，残缺表格静默跳过。
    """
    tables: list[list[list[str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # 表头行要求以 | 起止，且下一行是分隔行
        if _TABLE_ROW.match(line) and i + 1 < len(lines) and _is_separator_row(lines[i + 1]):
            table = [_split_cells(line)]  # 表头
            j = i + 2
            while j < len(lines) and _TABLE_ROW.match(lines[j]):
                table.append(_split_cells(lines[j]))
                j += 1
            if len(table) >= 2:  # 至少表头 + 一行数据才成表
                tables.append(table)
            i = j
            continue
        i += 1
    return tables


# ---------------------------------------------------------------- 清洗层（策略B：降级清洗，绝不抛错）

def _clean_cell(cell: str) -> str:
    """对单元格做降级清洗：解转义 → 剥 HTML → 压平换行 → 收尾空白。

    任何一步异常都退回原文（fail-soft）。
    """
    try:
        text = _CELL_ESCAPE.sub(r"\1", cell)
        text = _HTML_TAG.sub(" ", text)
        text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        return text.strip()
    except Exception:
        return cell


# ---------------------------------------------------------------- 编码层（策略B：宽松兼容Excel）

def _encode_field(field: str) -> str:
    """Excel 友好编码：含逗号或引号才加双引号包裹，引号翻倍；换行已在上层压平。

    字段内若仍有换行（理论上已被清洗层压平），此处兜底压成空格后再判断。
    """
    field = field.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if "," in field or '"' in field:
        return '"' + field.replace('"', '""') + '"'
    return field


def _row_to_csv(row: list[str], ncols: int) -> str:
    """一行转 CSV 文本：不足补空、超出截断（策略B：绝不抛错）。"""
    padded = (row + [""] * ncols)[:ncols]
    return ",".join(_encode_field(c) for c in padded) + "\r\n"


# ---------------------------------------------------------------- 主流程

def convert_md_file(md_path: str, out_dir: str | None = None) -> list[Path]:
    """转换一个 .md 文件，返回生成的 .csv 路径列表。

    第一张表 → <同名>.csv，第二张起 → <同名>_2.csv、<同名>_3.csv……
    """
    md = Path(md_path)
    tables = extract_tables(md.read_text(encoding="utf-8"))
    if not tables:
        print(f"⚠ 未在 {md.name} 中找到完整 Markdown 表格（需要表头行 + 分隔行 + 数据行）")
        return []

    base = (out_dir and Path(out_dir) or md.parent) / md.stem
    written: list[Path] = []
    for idx, table in enumerate(tables, start=1):
        out = base if idx == 1 else base.with_name(f"{base.name}_{idx}")
        out = out.with_suffix(".csv")
        ncols = len(table[0])
        with out.open("w", encoding="utf-8", newline="") as fh:
            fh.write(_row_to_csv([_clean_cell(c) for c in table[0]], ncols))  # 表头
            for row in table[1:]:
                fh.write(_row_to_csv([_clean_cell(c) for c in row], ncols))   # 数据行
        written.append(out)
        print(f"✅ {md.name} 第 {idx} 张表 → {out.name}（{len(table) - 1} 行数据 × {ncols} 列）")
    return written


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，先重配为 UTF-8（与 cli.py 同款处理）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 1:
        print(__doc__)
        return 2
    for arg in args:
        if not Path(arg).exists():
            print(f"❌ 文件不存在: {arg}")
            return 1
        convert_md_file(arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
