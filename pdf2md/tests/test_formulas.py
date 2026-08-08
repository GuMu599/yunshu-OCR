"""公式行拆分回归测试 — 修复多公式合并/截断"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz  # noqa: E402

from pdf2md import formulas  # noqa: E402


def _make_two_line_pdf():
    """合成一页: 上下两行文字之间有墨迹 (模拟两条堆叠公式)."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    # 两段正文 (文字层), 中间留空隙
    page.insert_text((100, 100), "Paragraph one here", fontsize=12)
    page.insert_text((100, 180), "Paragraph two here", fontsize=12)
    # 空隙内画两条粗黑线, 模拟两条公式的墨迹
    page.draw_line(fitz.Point(120, 130), fitz.Point(300, 130), width=3)
    page.draw_line(fitz.Point(120, 150), fitz.Point(280, 150), width=3)
    return doc, page


def test_split_ink_lines_splits_stacked_equations():
    doc, page = _make_two_line_pdf()
    # 空隙止于下一文本块顶缘 (y≈168), 不含下方文字
    gap = fitz.Rect(100, 105, 320, 162)
    lines = formulas.split_ink_lines(page, [gap.x0, gap.y0, gap.x1, gap.y1])
    assert len(lines) == 2, f"应拆成 2 条公式行, 得到 {len(lines)}: {lines}"
    # 两条线的 y 不同
    ys = sorted(r[1] for r in lines)
    assert ys[1] - ys[0] > 10
    doc.close()


def test_split_ink_lines_empty_gap():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 100), "only paragraph", fontsize=12)
    # 无墨迹的空隙
    lines = formulas.split_ink_lines(page, [100, 110, 400, 500])
    assert lines == []
    doc.close()


# ── pix2tex 假阳性守卫 ──

def test_roman_prose_not_formula():
    # \mathrm{...} 纯散文被误判为 formula → 不是真公式
    assert formulas.is_real_formula(r"{\mathrm{Sructure~of~Ibe~book}}.") is False


def test_giant_array_not_formula():
    arr = r"\begin{array}{c c c c c c c c c c c c c c c c c c c}1&2&3&4\end{array}"
    assert formulas.is_real_formula(arr) is False


def test_real_pix2tex_formulas_still_pass():
    assert formulas.is_real_formula(r"\mathbf{B}=\mu_{0}(1+\chi)\mathbf{H}") is True
    assert formulas.is_real_formula(r"m\frac{\mathrm{d}\mathbf{v}}{\mathrm{d}t}=-q\nabla V") is True
    assert formulas.is_real_formula(r"\mathrm{d}u=I\mathrm{d}\mathrm{S}. (1.1)") is True
    assert formulas.is_real_formula(r"\sigma\cdot{\bf a}=\left(\begin{array}{c c}a_3&a_1\end{array}\right)") is True
