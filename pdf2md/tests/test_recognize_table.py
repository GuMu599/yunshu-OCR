"""recognize_table 策略阶梯: 原生几何 / 图片表 OCR 救援 / 散文还原 / 模型缺失回退"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md import tables as tables_mod  # noqa: E402
from pdf2md.tables import WordItem  # noqa: E402


def _native_grid_page():
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    cells = [["H1", "H2"], ["a1", "a2"], ["b1", "b2"]]
    for ri, row in enumerate(cells):
        for ci, v in enumerate(row):
            page.insert_text(fitz.Point(50 + ci * 100, 50 + ri * 20), v, fontsize=10)
    return page


def _ocr_grid_items():
    """模拟图片表的 OCR 结果: 词级坐标 + 置信度 (右对齐数字列)."""
    items = [
        WordItem("Metric", 60.0, 40.0, 90.0, 50.0, 0.95),
        WordItem("Value", 240.0, 40.0, 250.0, 50.0, 0.95),
        WordItem("alpha", 60.0, 60.0, 90.0, 70.0, 0.94),
        WordItem("1", 247.0, 60.0, 250.0, 70.0, 0.90),
        WordItem("beta", 60.0, 80.0, 90.0, 90.0, 0.93),
        WordItem("123", 235.0, 80.0, 250.0, 90.0, 0.91),
    ]
    return items


def test_native_geometry_rescue():
    page = _native_grid_page()
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72)
    assert frag is not None
    assert frag["source"] == "geometry_native"
    assert frag["structure_quality"] >= 0.6
    assert "H1" in frag["markdown"]
    assert frag["html"] is not None


def test_bitmap_rescue_via_ocr_geometry(monkeypatch):
    page = fitz.open().new_page(width=400, height=400)  # 无原生文字
    monkeypatch.setattr(tables_mod, "ocr_word_items", lambda page_, rect, dpi=300: _ocr_grid_items())
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=300, do_ocr=True)
    assert frag is not None
    assert frag["source"] == "geometry_ocr"
    assert "alpha" in frag["markdown"]
    assert "123" in frag["markdown"]
    assert frag["confidence"] is not None  # OCR 置信度


def test_no_ocr_skips_bitmap_rescue(monkeypatch):
    page = fitz.open().new_page(width=400, height=400)
    monkeypatch.setattr(tables_mod, "ocr_word_items", lambda page_, rect, dpi=300: _ocr_grid_items())
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=300, do_ocr=False)
    assert frag is None  # 无原生文字且禁 OCR → 无结果


def test_prose_returns_none():
    doc = fitz.open()
    page = doc.new_page(width=500, height=300)
    lines = [
        "This is a long sentence that goes on and on across the page",
        "like normal prose text that fills a whole paragraph of words",
        "that just keeps flowing until the line reaches the right margin",
    ]
    for i, line in enumerate(lines):
        page.insert_text(fitz.Point(40, 50 + i * 15), line, fontsize=10)
    frag = tables_mod.recognize_table(page, [0, 0, 500, 300], dpi=72)
    assert frag is None  # 散文 → 由 pipeline 还原为正文文本


def test_model_missing_falls_back_gracefully():
    # 默认 table-model 适配器目录不存在 → available False → step5 短路, 不抛错
    page = _native_grid_page()
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72, use_model=True)
    assert frag is not None
    assert frag["source"] == "geometry_native"


def test_sane_text_table_rejects_hallucinated_columns():
    # 原生每行最多 4 词, 但 find_table_text 幻觉出 8 列 → 拒绝
    md = "|Col1|Col2|Col3|Col4|Col5|Col6|Col7|\n|---|" + "---|" * 6 + "\n|||||||\n"
    native = [
        WordItem("a", 0, 0, 10, 10), WordItem("b", 10, 0, 20, 10),
        WordItem("c", 0, 20, 10, 30), WordItem("d", 10, 20, 20, 30),
    ]
    assert tables_mod._sane_text_table(md, native) is False
    good = "| a | b |\n| --- | --- |\n| c | d |\n"
    assert tables_mod._sane_text_table(good, native) is True


def test_ocr_failure_is_contained(monkeypatch):
    """OCR 异常 → recognize_table 返回 None (不拖垮整份 PDF)."""
    import fitz

    page = fitz.open().new_page(width=400, height=400)

    def _boom(page_, rect, dpi=300):
        raise RuntimeError("rapidocr engine failed")

    monkeypatch.setattr(tables_mod, "ocr_word_items", _boom)
    assert tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=300, use_model=False) is None


def test_math_region_not_table():
    """公式区 (LaTeX 密集) → 不建表."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    formulas = [r"x = \int_0^1 f(x) dx", r"y = \frac{a}{b} + c", r"z = \sum_{i=1}^n i^2",
                r"w = \lim_{x\to 0} \frac{\sin x}{x}", r"v = \nabla \times \mathbf{F}"]
    for i, f in enumerate(formulas):
        page.insert_text(fitz.Point(40, 50 + i * 18), f, fontsize=10)
    assert tables_mod.recognize_table(page, [0, 0, 500, 500], dpi=72) is None


def test_graph_region_detected_and_degraded():
    # 大量曲线 → 图表, recognize_table 返回 None (不硬建成表格)
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    for i in range(60):
        page.draw_line(fitz.Point(50, 50 + i), fitz.Point(350, 100 + i * 2))
    page.insert_text(fitz.Point(60, 40), "axis")
    assert tables_mod._is_graph_region(page, [0, 0, 400, 400]) is True
    assert tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72) is None


def test_table_grid_not_graph():
    # 网格线个位数 → 不是图表, 正常走表格阶梯
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    for x in (50, 150, 250, 310):
        page.draw_line(fitz.Point(x, 38), fitz.Point(x, 120))
    for y in (38, 55, 75, 95, 120):
        page.draw_line(fitz.Point(50, y), fitz.Point(310, y))
    for ri, row in enumerate([["a", "b", "c"], ["1", "2", "3"]]):
        for ci, v in enumerate(row):
            page.insert_text(fitz.Point(55 + ci * 100, 50 + ri * 20), v, fontsize=10)
    assert tables_mod._is_graph_region(page, [0, 0, 400, 400]) is False
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72)
    assert frag is not None


def test_blank_merge_policy():
    from pdf2md.table_html import MERGE_BLANK

    page = _native_grid_page()
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72, merge_policy=MERGE_BLANK)
    assert frag is not None
