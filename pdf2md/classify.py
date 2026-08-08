"""内容分类 — 内容驱动规则, 不依赖 YOLO 类别。

移植自 yunshu-litwise/tools/layout_converter.py Phase 3。
与原文差异: 不丢弃任何内容 (AUTHOR_SKIP 也保留为普通文本), 满足"文字不丢失"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class ContentType(Enum):
    TITLE = auto()        # 论文标题 → # H1
    H2 = auto()           # 节标题 → ##
    H3 = auto()           # 小节 → ###
    H4 = auto()           # 子小节 → ####
    ABSTRACT = auto()     # 摘要正文
    KEYWORDS = auto()     # 关键词行
    AUTHOR = auto()       # 作者/机构/脚注(保留为文本)
    REFERENCE = auto()    # 参考文献条目
    BODY = auto()         # 普通段落


_INST_KW = [
    "University", "Hospital", "School", "Institute", "College",
    "Laboratory", "Department", "Academy", "大学", "医院", "学院",
    "科学院", "研究所", "实验室", "省", "市",
]

_SECTION_KW = {
    "引言", "实验部分", "实验", "结果与讨论", "结果和讨论", "实验与讨论",
    "结论", "参考文献", "Introduction", "Experimental", "Experiment",
    "Results and Discussion", "Results", "Conclusion", "References",
    "Background", "Method", "Model Architecture", "Training",
    "Related Work", "Abstract", "Acknowledgements",
    "Discussion", "Evaluation", "Experiments", "Implementation",
    "Preface", "Foreword", "Contents", "Introduction", "Conclusion",
    "前言", "目录", "致谢",
    "摘要",
}

_BOILERPLATE = [
    "http", "DOI:", "doi:", "CCDC:", "Received", "收稿",
    "中图分类号", "文献标识码", "文章编号", "通讯联系人", "Copyright", "©",
]


@dataclass
class RegionFeatures:
    text: str
    clean_text: str
    char_count: int
    word_count: int
    line_count: int
    avg_line_len: float
    cjk_ratio: float
    latin_ratio: float
    digit_ratio: float
    page_num: int
    y: float
    x_center: float
    width: float
    is_wide: bool
    is_page_top: bool
    visual_class: str
    starts_with_digit_section: bool
    starts_with_section_number: bool
    starts_with_abstract: bool
    starts_with_keywords: bool
    has_author_marker: bool
    has_inst_keyword: bool
    has_delimiter: bool
    author_marker_count: int
    starts_with_ref_bracket: bool
    is_boilerplate: bool


def extract_features(raw_text: str, bbox: list[float], page_num: int, page_w: float, page_h: float, visual_class: str) -> RegionFeatures:
    text = raw_text
    clean = re.sub(r"\s+", " ", text).strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    char_count = len(clean)
    word_count = len(clean.split()) if clean else 0
    line_count = len(lines)
    avg_line_len = sum(len(l) for l in lines) / max(line_count, 1)

    total = max(char_count, 1)
    cjk_ratio = sum(1 for c in clean if "一" <= c <= "鿿") / total
    latin_ratio = sum(1 for c in clean if c.isascii() and c.isalpha()) / total
    digit_ratio = sum(1 for c in clean if c.isdigit()) / total

    width = bbox[2] - bbox[0]
    y = bbox[1]
    x_center = (bbox[0] + bbox[2]) / 2

    starts_with_digit_section = bool(re.match(r"^[\d]+(\.[\d]+)+\s", clean))
    _sec = re.match(r"^(\d+)\s", clean)
    starts_with_section_number = False
    if _sec:
        num = int(_sec.group(1))
        after = clean[_sec.end():].strip()
        if 0 <= num <= 20 and not re.match(r"^\d", after):
            starts_with_section_number = True
    starts_with_abstract = clean.startswith("摘要") or clean.startswith("Abstract")
    starts_with_keywords = clean.startswith("关键词") or clean.startswith("Keywords")
    has_author_marker = "∗" in text or "@" in text
    has_inst_keyword = any(kw in text for kw in _INST_KW)
    has_delimiter = bool(re.search(r"[,;，；]", text))
    author_marker_count = text.count("∗") + text.count("*")
    starts_with_ref_bracket = bool(re.match(r"^\[\d+\]", clean))
    is_boilerplate = any(bp in text for bp in _BOILERPLATE)

    return RegionFeatures(
        text=text, clean_text=clean, char_count=char_count,
        word_count=word_count, line_count=line_count, avg_line_len=avg_line_len,
        cjk_ratio=cjk_ratio, latin_ratio=latin_ratio, digit_ratio=digit_ratio,
        page_num=page_num, y=y, x_center=x_center, width=width,
        is_wide=width > page_w * 0.6, is_page_top=y < page_h * 0.25,
        visual_class=visual_class,
        starts_with_digit_section=starts_with_digit_section,
        starts_with_section_number=starts_with_section_number,
        starts_with_abstract=starts_with_abstract,
        starts_with_keywords=starts_with_keywords,
        has_author_marker=has_author_marker, has_inst_keyword=has_inst_keyword,
        has_delimiter=has_delimiter, author_marker_count=author_marker_count,
        starts_with_ref_bracket=starts_with_ref_bracket, is_boilerplate=is_boilerplate,
    )


def _looks_like_toc_block(text: str) -> bool:
    """目录块/合并标题检测.

    目录条目形如 "1.1 Magnetic moments 1" (标题后跟页码), 或一个文本块里
    塞了多个节号 ("1.1.1 … 1.1.2 …")。真实标题不会有这两种形态。
    """
    clean = re.sub(r"\s+", " ", str(text)).strip()
    prefixes = re.findall(r"\b\d+(?:\.\d+)+\s", clean)
    if len(prefixes) >= 2:
        return True
    m = re.match(r"^(\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)\s*$", clean)
    if m:
        title_tail = m.group(2)
        # 标题部分不再含数字 → 结尾数字是目录页码, 不是小节号
        if not re.search(r"\d", title_tail):
            return True
    return False


def classify(f: RegionFeatures) -> ContentType:
    """分类: 规则顺序匹配, 第一条命中即返回. 不丢弃任何内容."""
    if f.starts_with_abstract:
        return ContentType.ABSTRACT
    if f.starts_with_keywords:
        return ContentType.KEYWORDS
    if f.is_boilerplate:
        return ContentType.AUTHOR
    # 作者/机构/脚注: 短行 + 机构词/分隔符/标记 → 保留为文本
    if (f.has_inst_keyword and f.has_delimiter and f.char_count < 350) or \
       (f.author_marker_count >= 3 and f.has_delimiter and f.char_count < 350) or \
       (f.has_author_marker and not f.has_inst_keyword):
        return ContentType.AUTHOR
    # 目录块/合并标题 → 正文 (真实标题是单条、无页码)
    if _looks_like_toc_block(f.clean_text):
        return ContentType.BODY
    if f.starts_with_digit_section:
        return ContentType.H3
    # 标题必须短: 中文 word_count 恒为1, 用字符数判短 (≤40 字), 防止正文误判
    if f.starts_with_section_number and f.char_count <= 40:
        return ContentType.H2
    for kw in _SECTION_KW:
        if kw in f.clean_text and f.char_count <= 40:
            return ContentType.H2
    if f.starts_with_ref_bracket:
        return ContentType.REFERENCE
    return ContentType.BODY


def looks_like_title(f: RegionFeatures) -> bool:
    if f.cjk_ratio > 0.1:
        return 10 <= f.char_count <= 100 and not f.clean_text.endswith("。")
    return 4 <= f.word_count <= 25 and not f.clean_text.endswith(".")


def format_region(f: RegionFeatures, content_type: ContentType) -> str:
    """按类型生成 markdown 文本."""
    text = f.clean_text
    if content_type == ContentType.TITLE:
        return f"# {text}"
    if content_type == ContentType.H2:
        return f"## {text}"
    if content_type == ContentType.H3:
        return f"### {text}"
    if content_type == ContentType.H4:
        return f"#### {text}"
    if content_type == ContentType.REFERENCE:
        return text if text.startswith("[") else f"> {text}"
    # ABSTRACT / KEYWORDS / AUTHOR / BODY → 普通文本
    return text


# 第 1 页 (元数据页) 排序优先级
PAGE0_ORDER = {
    ContentType.TITLE: 0, ContentType.AUTHOR: 1, ContentType.ABSTRACT: 2,
    ContentType.KEYWORDS: 3, ContentType.H2: 4, ContentType.H3: 5,
    ContentType.H4: 6, ContentType.BODY: 7, ContentType.REFERENCE: 8,
}
