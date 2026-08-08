"""内容分类回归测试 — 针对用户报告的标题误判"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import classify  # noqa: E402


def _feat(text: str, visual_class: str = "text", page: int = 5):
    bbox = [40.0, 200.0, 540.0, 240.0]
    return classify.extract_features(text, bbox, page, 595.0, 742.0, visual_class)


def test_chinese_body_with_keyword_not_heading():
    # 中文段落 word_count 恒为 1, 含"实验"也不能变成 H2 (用户报告的核心 bug)
    text = "子异构体[22]。系统探究三者组合规律，不仅能明晰配体结构-配合物拓扑的构效关系，更为定向设计具有特定孔道、光学或磁学性能的配合物材料提供理论支撑与实验依据。"
    assert classify.classify(_feat(text)) == classify.ContentType.BODY


def test_english_long_paragraph_not_heading():
    text = "This book is about the manifestation of magnetism in condensed matter. Solids contain magnetic moments which can act together in a cooperative way and lead to behaviour that is quite different from what would be observed if all the magnetic moments were isolated from one another."
    assert classify.classify(_feat(text)) == classify.ContentType.BODY


def test_toc_merged_block_not_heading():
    text = "1.1.1 Magnetic moments and angular momentum 1.1.2 Precession 1.1.3 The Bohr magneton 1.1.4 Magnetization and field 1.2 Classical mechanics and magnetic moments"
    assert classify.classify(_feat(text)) == classify.ContentType.BODY


def test_toc_entry_with_page_number_not_heading():
    text = "1.1 Magnetic moments 1"
    assert classify.classify(_feat(text)) == classify.ContentType.BODY


def test_real_section_heading_still_heading():
    assert classify.classify(_feat("1.1 Magnetic moments")) == classify.ContentType.H3
    assert classify.classify(_feat("1 实验部分")) == classify.ContentType.H2
    assert classify.classify(_feat("2 结果与讨论")) == classify.ContentType.H2
