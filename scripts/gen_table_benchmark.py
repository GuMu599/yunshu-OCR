"""生成表格识别基准: 真实数据表 PDF + 精确 gold (HTML/MD) + manifest.jsonl.

gold 由内部 Table 直接导出 → 真值精确 (构造即真值)。
样本覆盖:
  简单 (几何阶梯可解): 基础网格 / 右对齐数字列 / 空格与参差 / 位图嵌入
  复杂 (结构模型目标): 合并表头 (colspan)
运行后产物在 tests/benchmarks/tables/ 下, 供 pdf2md.benchmark 消费。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402

from pdf2md.table_html import (  # noqa: E402
    Table,
    TableCell,
    make_table,
    table_to_html,
    table_to_md,
)

_REPO = Path(__file__).resolve().parent.parent
_OUT = _REPO / "tests" / "benchmarks" / "tables" / "synth"
_MANIFEST = _REPO / "tests" / "benchmarks" / "tables" / "manifest.jsonl"

_FONT = fitz.Font("helv")
_FONT_SIZE = 10
_ASC = 11.5  # 上行高度 (基线到顶)
_DESC = 3.0  # 下行深度


def _draw_table(page, table: Table, col_x0, col_right, row_y, align=None) -> None:
    """按列边界/行基线把表格文字画到页面上 (仅锚点; 合并覆盖位置不画)."""
    right_cols = {c for c, a in enumerate(align or []) if a == "right"}
    for (r, c), cell in table.cells.items():
        y = row_y[r]
        if c in right_cols:
            w = _FONT.text_length(cell.text, fontsize=_FONT_SIZE)
            x = col_right[c] - w
        else:
            x = col_x0[c]
        page.insert_text(fitz.Point(x, y), cell.text, fontsize=_FONT_SIZE)


def _table_rect(col_x0, col_right, row_y) -> list[float]:
    return [
        min(col_x0),
        min(row_y) - _ASC,
        max(col_right),
        max(row_y) + _DESC,
    ]


# ---------------------------------------------------------------------------
# 样本定义
# ---------------------------------------------------------------------------


def _samples() -> list[dict]:
    out = []

    t = make_table(
        [["Col A", "Col B", "Col C"], ["1.5", "x", "p"], ["2.0", "y", "q"], ["3.5", "z", "r"]]
    )
    out.append({"name": "synth_grid", "kind": "simple", "table": t,
                "col_x0": [50, 150, 250], "col_right": [110, 210, 310], "row_y": [50, 72, 94, 116]})

    t = make_table(
        [["Item", "Value"], ["alpha", "1"], ["beta", "123"], ["gamma", "10"], ["delta", "5678"]]
    )
    t.align = [None, "right"]
    out.append({"name": "synth_numeric_right", "kind": "simple", "table": t,
                "col_x0": [50, 200], "col_right": [180, 250], "row_y": [50, 72, 94, 116, 138]})

    t = make_table([["A", "B"], ["1", ""], ["2", "y"], ["", "z"]])
    out.append({"name": "synth_empty_ragged", "kind": "simple", "table": t,
                "col_x0": [50, 150], "col_right": [110, 210], "row_y": [50, 72, 94, 116]})

    cells = {
        (0, 0): TableCell(0, 0, colspan=2, text="Group"),
        (0, 2): TableCell(0, 2, text="Total"),
        (1, 0): TableCell(1, 0, text="x"),
        (1, 1): TableCell(1, 1, text="1"),
        (1, 2): TableCell(1, 2, text="2"),
        (2, 0): TableCell(2, 0, text="y"),
        (2, 1): TableCell(2, 1, text="3"),
        (2, 2): TableCell(2, 2, text="4"),
    }
    t = Table(3, 3, cells)
    out.append({"name": "synth_merged_header", "kind": "complex", "table": t,
                "col_x0": [50, 120, 190], "col_right": [110, 180, 250], "row_y": [50, 72, 94]})
    return out


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------


def _write_native(name: str, spec: dict) -> list[float]:
    """原生文字表 PDF (几何重建走 native_word_items 路径)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    _draw_table(page, spec["table"], spec["col_x0"], spec["col_right"], spec["row_y"], spec["table"].align)
    rect = _table_rect(spec["col_x0"], spec["col_right"], spec["row_y"])
    path = _OUT / f"{name}.pdf"
    doc.save(path)
    doc.close()
    return rect


def _write_bitmap(name: str, spec: dict) -> list[float]:
    """把表格渲染成位图再嵌入 → 无原生文字 (OCR 救援路径的端到端样本)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    _draw_table(page, spec["table"], spec["col_x0"], spec["col_right"], spec["row_y"], spec["table"].align)
    rect = _table_rect(spec["col_x0"], spec["col_right"], spec["row_y"])
    scale = 3  # 高清渲染
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=fitz.Rect(rect))
    png = pix.tobytes("png")

    doc2 = fitz.open()
    page2 = doc2.new_page(width=400, height=300)
    page2.insert_image(fitz.Rect(rect), stream=png)
    path = _OUT / f"{name}.pdf"
    doc2.save(path)
    doc2.close()
    doc.close()
    return rect


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in _samples():
        table: Table = spec["table"]
        for suffix, writer in (("", _write_native), ("_bitmap", _write_bitmap)):
            name = f"{spec['name']}{suffix}"
            rect = writer(name, spec)
            records.append({
                "name": name,
                "pdf": f"tests/benchmarks/tables/synth/{name}.pdf",
                "page": 1,
                "bbox": [round(v, 1) for v in rect],
                "gold_html": table_to_html(table),
                "gold_md": table_to_md(table),
                "kind": spec["kind"],
            })
    with open(_MANIFEST, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"生成 {len(records)} 个样本 → {_OUT}")
    print(f"manifest → {_MANIFEST}")


if __name__ == "__main__":
    main()
