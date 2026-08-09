"""真实样本回归: APS 论文 Table 1 (无框跨页表, 11 列) 提取正确性.

依赖本地 测试文件/aps.74.20250574.pdf (gitignored, 缺失则跳过)。
固化: ①检测器产出整表候选 ②C11/C12 不被页脚桥接合并 ③跨页合并。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

_PDF = Path(__file__).resolve().parent.parent.parent / "测试文件" / "aps.74.20250574.pdf"

pytestmark = pytest.mark.skipif(not _PDF.exists(), reason="需要 测试文件/aps.74.20250574.pdf")

import fitz  # noqa: E402

from pdf2md.table_html import parse_html_table  # noqa: E402
from pdf2md.tables import (  # noqa: E402
    detect_text_table_candidates,
    merge_table_items,
    recognize_table,
)


@pytest.fixture(scope="module")
def doc():
    return fitz.open(str(_PDF))


def test_detect_whole_table_candidate(doc):
    cands = detect_text_table_candidates(doc[3])
    assert len(cands) == 1
    c = cands[0]
    assert c[1] < 100  # 覆盖表头
    assert c[3] < 775  # 不含页脚 (页码会桥接列)


def test_eleven_columns_not_bridged(doc):
    cands = detect_text_table_candidates(doc[3])
    frag = recognize_table(doc[3], cands[0], dpi=300, use_model=False)
    assert frag is not None
    assert frag["source"] == "geometry_native"
    t = parse_html_table(frag["html"])
    assert t.cols == 11  # 页脚不桥接 C11/C12
    header = [t.text_at(0, c) for c in range(t.cols)]
    assert "C11" in header and "C12" in header  # 两列分开
    assert "39.80" in [t.text_at(1, c) for c in range(t.cols)]  # f-band 行 B/GPa


def test_cross_page_merge(doc):
    c4 = detect_text_table_candidates(doc[3])[0]
    c5 = detect_text_table_candidates(doc[4])[0]
    f4 = recognize_table(doc[3], c4, dpi=300, use_model=False)
    f5 = recognize_table(doc[4], c5, dpi=300, use_model=False)
    assert f4 is not None and f5 is not None
    merged = merge_table_items(f4, f5)
    assert merged is not None
    t = parse_html_table(merged["html"])
    t4 = parse_html_table(f4["html"])
    assert t.rows > t4.rows  # 合并后行数增加
    assert t.cols == 11
