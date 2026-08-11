"""公式行拆分回归测试 — 修复多公式合并/截断"""

import sys
import io
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from pdf2md import formulas  # noqa: E402


def test_formula_model_recognition_is_reproducible_and_restores_rng(monkeypatch):
    class RandomizedRecognizer:
        def __call__(self, image):
            return f"x={random.random():.8f}+{np.random.random():.8f}+{torch.rand(1).item():.8f}"

    image = Image.new("RGB", (8, 8), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    monkeypatch.setattr(formulas.FormulaModel, "_ensure", classmethod(lambda cls: True))
    monkeypatch.setattr(formulas.FormulaModel, "_model", RandomizedRecognizer())

    random.seed(123)
    np.random.seed(123)
    torch.manual_seed(123)
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    torch_state = torch.random.get_rng_state().clone()

    first = formulas.FormulaModel.recognize(buffer.getvalue())
    second = formulas.FormulaModel.recognize(buffer.getvalue())

    assert first == second
    assert random.getstate() == python_state
    current_numpy = np.random.get_state()
    assert current_numpy[0] == numpy_state[0]
    assert np.array_equal(current_numpy[1], numpy_state[1])
    assert current_numpy[2:] == numpy_state[2:]
    assert torch.equal(torch.random.get_rng_state(), torch_state)


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
    assert formulas.is_real_formula(r"x\in\left[0,1\right)") is True


def test_pix2tex_result_does_not_invent_a_confidence_score(monkeypatch):
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((20, 50), "x = y", fontsize=12)
    monkeypatch.setattr(formulas.FormulaModel, "available", classmethod(lambda cls: True))
    monkeypatch.setattr(
        formulas.FormulaModel,
        "recognize",
        classmethod(lambda cls, png_bytes: "x = y"),
    )

    latex, confidence, engine = formulas.ocr_formula_latex(
        page, [10, 20, 100, 70], use_model=True
    )

    assert latex == "x = y"
    assert confidence is None
    assert engine == "pix2tex"
    doc.close()


def test_structurally_incomplete_latex_is_rejected():
    assert formulas.is_real_formula(r"\mu_{2 ,") is False
    assert formulas.is_real_formula(r"\Delta x = \alpha_{i}") is True
    assert formulas.is_real_formula(r"\begin{array}{c}x=y") is False
    assert formulas.is_real_formula(
        r"\begin{array}{c c}X&\stackrel{\leftarrow}{\longrightarrow}\end{array}"
    ) is False


def test_native_equation_text_recovers_indexed_stacked_equation():
    raw = "Δ( X1，t －珔\\nXt) = α1 + β1( X1，t －1 －珔\\nXt －1) + ∑\\nk\\nj = 1θ1，jΔ( X1，t －j －珔\\nXt －j) + μ1，t\\n，; (\\n)"

    latex = formulas.native_formula_latex(raw)

    assert latex is not None
    assert r"\Delta" in latex
    assert r"X_{1,t-1}" in latex
    assert r"\bar{X}_{t-1}" in latex
    assert r"\sum_{j=1}^{k}\theta_{1,j}" in latex
    assert r"\mu_{1,t}" in latex
    assert "SUB" not in latex
    assert not latex.endswith("( )")


def test_native_fourier_equation_recovers_trigonometric_fraction():
    raw = "Δ( X1，t －Xt) = α1 + β1( X1，t －1 －Xt －1) + c1sin 2πkt ( ) T + d1cos 2πkt ( ) T + ε1，t"

    latex = formulas.native_formula_latex(raw)

    assert latex is not None
    assert r"X_{1,t} - X_{t}" in latex
    assert r"c_{1}\sin\left(\frac{2\pi k t}{T}\right)" in latex
    assert r"d_{1}\cos\left(\frac{2\pi k t}{T}\right)" in latex


def test_stacked_formula_region_is_split_with_script_padding():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x_i = 1", fontsize=12)
    page.insert_text((100, 165), "y_i = 2", fontsize=12)
    page.insert_text((100, 200), "z_i = 3", fontsize=12)
    rect = [80, 105, 300, 215]

    parts = formulas.formula_region_parts(page, rect, "x_i = 1\ny_i = 2\nz_i = 3")

    assert len(parts) == 3
    assert parts[0][1] < 125
    assert parts[0][3] > 132
    doc.close()


def test_inline_equalities_become_latex_without_touching_dates():
    text = (
        "扫描日期为2012-01-30，根据布拉格方程2dsinθ = nλ，"
        "管电压40 kV，λ = 0. 154 nm，且R =3r，"
        "βj = ρj - 1，t = m + 1，g = 9.8m●s 2。"
    )

    formatted, count = formulas.format_inline_formulas(text)

    assert "2012-01-30" in formatted
    assert "$2d\\sin\\theta = n\\lambda$" in formatted
    assert "$\\lambda = 0.154\\,\\mathrm{nm}$" in formatted
    assert "$R = 3r$" in formatted
    assert r"$\beta_{j} = \rho_{j} - 1$" in formatted
    assert r"$t = m + 1$" in formatted
    assert r"$g = 9.8\,\mathrm{m}\cdot\mathrm{s}^{-2}$" in formatted
    assert count == 6


def test_inline_formatter_ignores_prose_and_plain_arithmetic():
    text = "本文选取10 + 3个国家，时间为2000年5月6日，图3展示结果。"

    assert formulas.format_inline_formulas(text) == (text, 0)


def test_inline_formatter_skips_native_stacked_equation_text():
    text = "Δ(X1,t) = α1 + ∑\\nk\\nj = 1θ1,jΔ(X1,t-j)\\nΔ(X2,t) = α2"

    assert formulas.format_inline_formulas(text) == (text, 0)
