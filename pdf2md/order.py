"""阅读顺序 + 页眉页脚识别.

移植自 litwise-unified/tools/reading_order.py:
- order_page_elements: 宽元素优先 → 左栏(上→下) → 右栏(上→下)
- classify_margins: 跨页重复的顶部/底部文本 → header/footer (默认标注保留)
"""

from __future__ import annotations

import re
from collections import Counter
import fitz
from copy import deepcopy


def _vertical_key(item: dict):
    return item["bbox_pdf"][1], item["bbox_pdf"][0]


def _center_x(item: dict) -> float:
    box = item["bbox_pdf"]
    return (box[0] + box[2]) / 2


def _width(item: dict) -> float:
    box = item["bbox_pdf"]
    return box[2] - box[0]


def _normalized(text) -> str:
    return re.sub(r"\s+|\d+", "", str(text).lower())


def order_page_elements(elements: list[dict], *, page_width: float, gutter_mid=None) -> list[dict]:
    """按版面阅读顺序重排一页元素, 写入 reading_order (1-based).

    栏感知: 双栏页左栏读完再右栏, 通栏元素按其 y 作分隔带插入 (不再全部置顶)。
    gutter_mid: 调用方用块级 page_gutter_mid() 预计算 (块多更稳健), 缺省自行检测。
    """
    from .reading_order import reading_order_rank

    rows = [deepcopy(item) for item in elements]
    if not rows:
        return rows
    page_rect = fitz.Rect(0, 0, page_width, max(i["bbox_pdf"][3] for i in rows) + 1)
    boxes = [item["bbox_pdf"] for item in rows]
    visual_anchors = [
        item["bbox_pdf"] for item in rows
        if item.get("type") in {"image", "table", "table_image", "formula"}
    ]
    structural_anchors = [
        item["bbox_pdf"] for item in rows
        if item.get("type") == "text"
        and item["bbox_pdf"][3] - item["bbox_pdf"][1] <= 40.0
        and len(str(item.get("text") or "")) <= 80
        and re.match(r"^\s*(?:[1-9]|1[0-9]|20)(?:[.．]\d+)*\s+\S", str(item.get("text") or ""))
    ]
    rank = reading_order_rank(
        boxes,
        page_rect,
        gutter_mid=gutter_mid,
        visual_anchors=visual_anchors,
        structural_anchors=structural_anchors,
    )
    ordered = sorted(rows, key=lambda i: rank.get(id(i["bbox_pdf"]), 0))
    for index, item in enumerate(ordered, 1):
        item["reading_order"] = index
    return ordered


def classify_margins(pages: list[list[dict]], *, page_heights: list[float]) -> list[list[dict]]:
    """跨页重复的顶部/底部文本 → header/footer. 只在 text 元素上标记.

    每页用自己的高度 (封面与正文页尺寸可能不同)。
    """
    result = deepcopy(pages)
    bands = [h * 0.12 for h in page_heights]
    top = Counter(
        _normalized(i.get("text", ""))
        for idx, page in enumerate(result)
        for i in page
        if i["bbox_pdf"][1] <= bands[idx]
    )
    bottom = Counter(
        _normalized(i.get("text", ""))
        for idx, page in enumerate(result)
        for i in page
        if i["bbox_pdf"][3] >= page_heights[idx] - bands[idx]
    )
    # 节级行眉只在本节出现 (5-8页), 阈值不能是全书一半
    threshold = max(2, len(result) // 6 + 1)
    for idx, page in enumerate(result):
        band = bands[idx]
        for item in page:
            key = _normalized(item.get("text", ""))
            if item.get("type") == "text" and item["bbox_pdf"][1] <= band and top[key] >= threshold:
                item["type"] = "header"
            elif item.get("type") == "text" and item["bbox_pdf"][3] >= page_heights[idx] - band and bottom[key] >= threshold:
                item["type"] = "footer"
    return result
