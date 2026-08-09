"""无框表候选检测 + 散文/表判别"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md import tables as tables_mod  # noqa: E402
from pdf2md.table_html import make_table, table_to_html  # noqa: E402


def _table_page():
    """简单无框表 (每行一格 block) + 上方题注."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text(fitz.Point(50, 30),
                     "Table 1. This is a long caption line that spans the whole width of the page", fontsize=10)
    for ri, row in enumerate([["Method", "B/GPa"], ["f-band", "39.8"], ["PBE", "29.2"],
                              ["GGA", "30.2"], ["Expt", "14.8"], ["PBE+U", "27.2"]]):
        for ci, v in enumerate(row):
            page.insert_text(fitz.Point(60 + ci * 80, 60 + ri * 18), v, fontsize=10)
    return page


def test_detect_candidate_simple_table_excludes_caption():
    page = _table_page()
    cands = tables_mod.detect_text_table_candidates(page)
    assert len(cands) == 1
    c = cands[0]
    assert c[1] > 45  # 题注 (y30) 不在候选内
    assert c[0] < 70  # 覆盖表格左缘


def test_detect_candidate_prose_none():
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    lines = [
        "This is a long prose line that keeps going across the full width of the page",
        "and here is another sentence that is also very long and verbose indeed",
        "yet another line of flowing text that never seems to end at all",
        "the final paragraph line continues onward without any real point",
        "prose continues here with more words than any table would ever have",
    ]
    for i, line in enumerate(lines):
        page.insert_text(fitz.Point(40, 50 + i * 15), line, fontsize=10)
    assert tables_mod.detect_text_table_candidates(page) == []


def test_block_table_like_caption_rejected():
    assert tables_mod._block_table_like("表 1 实验与理论计算的镧系元素弹性性质") is False
    assert tables_mod._block_table_like("Table 1. Calculated elastic constants") is False
    assert tables_mod._block_table_like("Fig. 2 计算结果") is False
    assert tables_mod._block_table_like("f-band 39.80 33.24 63.20 28.10 50.90 — — 1.19 This work") is True


def test_candidate_excludes_page_footer():
    # 页脚 (页码) 横跨列会桥接合并 (如 "157102-4" 并 C11/C12), 候选必须排除页脚
    doc = fitz.open()
    page = doc.new_page(width=500, height=842)
    for ri, row in enumerate([["Method", "B/GPa"], ["f-band", "39.8"], ["PBE", "29.2"],
                              ["GGA", "30.2"], ["Expt", "14.8"]]):
        for ci, v in enumerate(row):
            page.insert_text(fitz.Point(60 + ci * 80, 700 + ri * 16), v, fontsize=10)
    page.insert_text(fitz.Point(280, 782), "157102-4", fontsize=10)  # 底部 8% 内页脚
    cands = tables_mod.detect_text_table_candidates(page)
    assert len(cands) == 1
    c = cands[0]
    assert c[3] < 775  # 候选不含页脚 (y > 775)
    assert c[3] > 730  # 但包含表格末行


def test_prose_like_table():
    # 真表 (短细胞) → False
    t = make_table([["Method", "B/GPa"], ["f-band", "39.8"], ["Expt", "14.8"]])
    frag = {"html": table_to_html(t)}
    assert tables_mod._prose_like_table(frag) is False
    # 双栏散文当表 (长细胞) → True
    prose = make_table([["物理性质的认识有助于理解多组分体系的性能", "另一方面, 声速等弹性性质还反映了物质微观结构"]])
    assert tables_mod._prose_like_table({"html": table_to_html(prose)}) is True
    # 无 html → 不判散文
    assert tables_mod._prose_like_table({"markdown": "| x |"}) is False
