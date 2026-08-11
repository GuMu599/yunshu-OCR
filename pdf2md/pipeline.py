"""主编排: YOLO 版面 → 提取 → 分类 → 公式/表格/图片 → 排序+页眉页脚 → 规范 → 文字不丢失.

convert_pdf() 是唯一入口, 返回报告 dict。
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter
from contextlib import contextmanager
from functools import wraps

import fitz

from . import classify, formulas, layout as layout_mod, normalize, ocr as ocr_mod, order as order_mod
from . import pdf_profile, reading_order, sidecar, table_model, tables as tables_mod, text as text_mod, textloss, visual
from .geometry import intersect_area, overlaps_any
from .resources import ConversionLimits, ResourceLimitError, run_isolated_conversion
from .table_html import MERGE_EXPAND
from .table_detect import split_table_region_by_captions


MIN_PIX2TEX_FORMULAS = 1


def _use_formula_model(formula_engine: str, *, detected_formulas: int) -> bool:
    """Correctness wins over model-startup cost whenever a formula exists."""
    if formula_engine == "pix2tex":
        return True
    if formula_engine == "rapidocr":
        return False
    return detected_formulas >= MIN_PIX2TEX_FORMULAS


def preflight(
    layout_model_path=None,
    *,
    layout_model_sha256: str | None = None,
    use_table_model: bool = True,
    do_ocr: bool = True,
    formula_engine: str = "auto",
    strict: bool = False,
) -> dict:
    """Report all local conversion dependencies without initializing inference engines."""
    result = {
        "layout": layout_mod.preflight_layout_model(
            layout_model_path, expected_sha256=layout_model_sha256
        ),
        "warnings": [],
    }
    result["ocr"] = ocr_mod.adapter_status() if do_ocr else {"available": False, "disabled": True}
    result["table"] = table_model.adapter_status() if use_table_model else {"available": False, "disabled": True}
    result["formula"] = (
        formulas.FormulaModel.checkpoint_status()
        if formula_engine != "rapidocr"
        else {"available": False, "disabled": True}
    )
    failures = []
    for name in ("ocr", "table", "formula"):
        component = result[name]
        if not component.get("available") and not component.get("disabled"):
            result["warnings"].append(name)
            failures.append(name)
    if strict and failures:
        raise RuntimeError(
            f"model_missing_or_invalid:{','.join(failures)}; "
            "run: python -m pdf2md.models install"
        )
    return result


@contextmanager
def _offline_environment(enabled: bool):
    keys = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "NO_ALBUMENTATIONS_UPDATE")
    previous = {key: os.environ.get(key) for key in keys}
    if enabled:
        for key in keys:
            os.environ[key] = "1"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _offline_guard(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _offline_environment(bool(kwargs.get("offline", True))):
            return function(*args, **kwargs)
    return wrapped


def _is_textlike(vc: str) -> bool:
    return vc in ("text", "title", "abstract", "list", "reference", "unknown")



def _item_id(page: int, kind: str, n: int) -> str:
    return f"p{page:03d}-{kind}-{n:03d}"


def _norm2(text) -> str:
    """规范化页眉文本: 去数字/空白/标点, 小写. 用于跨页重复匹配."""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    s = " ".join(lines[:2])
    return re.sub(r"[\d\s.·,;:()\[\]'\"\-]+", "", s.lower())


def _repeated_margins(doc, n_pages: int) -> tuple[set[str], set[str]]:
    """基于文字层找跨页重复的页眉/页脚 (规范化文本集合).

    节级行眉只在本节出现 (5-8页), 阈值取全书 1/6。
    """
    top: Counter[str] = Counter()
    bottom: Counter[str] = Counter()
    for i in range(n_pages):
        page = doc[i]
        h = page.rect.height
        band = h * 0.12
        tops: set[str] = set()
        bottoms: set[str] = set()
        for b in page.get_text("blocks"):
            if b[6] != 0 or not b[4].strip():
                continue
            if b[1] <= band:
                tops.add(_norm2(b[4]))
            if b[3] >= h - band:
                bottoms.add(_norm2(b[4]))
        top.update(tops)
        bottom.update(bottoms)
    thr = max(2, n_pages // 10 + 1)
    return (
        {k for k, c in top.items() if c >= thr and len(k) >= 3},
        {k for k, c in bottom.items() if c >= thr and len(k) >= 3},
    )


def _text_already_present(items: list[dict], raw: str) -> bool:
    """当前页是否已有几乎相同的文本项 (YOLO 散文区/表格区重叠时的去重)."""
    probe = re.sub(r"\s+", "", raw).lower()[:40]
    if len(probe) < 10:
        return False
    for it in items:
        if it.get("type") == "text" and probe in re.sub(r"\s+", "", str(it.get("text", ""))).lower():
            return True
    return False


def _dedup_text_key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(text or "")).lower()


def _deduplicate_page_items(items: list[dict]) -> tuple[list[dict], int]:
    """Remove repeated extracted text after all region branches have completed."""
    seen: list[tuple[str, list[float]]] = []
    out: list[dict] = []
    removed = 0
    for item in items:
        if item.get("type") not in ("text", "header", "footer"):
            out.append(item)
            continue
        key = _dedup_text_key(item.get("text", ""))
        if not key:
            out.append(item)
            continue
        rect = item.get("bbox_pdf", [0, 0, 0, 0])
        duplicate = False
        for prior_key, prior_rect in seen:
            if min(len(key), len(prior_key)) < 10:
                contains = key == prior_key
            else:
                contains = key in prior_key or prior_key in key
            vertical_overlap = min(rect[3], prior_rect[3]) - max(rect[1], prior_rect[1])
            min_height = max(1.0, min(rect[3] - rect[1], prior_rect[3] - prior_rect[1]))
            horizontal_overlap = min(rect[2], prior_rect[2]) - max(rect[0], prior_rect[0])
            min_width = max(1.0, min(rect[2] - rect[0], prior_rect[2] - prior_rect[0]))
            if contains and horizontal_overlap / min_width >= 0.5 and vertical_overlap / min_height >= 0.5:
                duplicate = True
                break
        if duplicate:
            removed += 1
            continue
        seen.append((key, rect))
        out.append(item)
    return out, removed


def _remove_formula_text_duplicates(
    page, items: list[dict], formula_rects: list[list[float]], *,
    gutter_mid, page_num: int, page_width: float, page_height: float,
) -> tuple[list[dict], int, int]:
    """Remove native glyphs already represented by accepted formula output."""
    if not formula_rects:
        return items, 0, 0

    cleaned_items: list[dict] = []
    removed = 0
    failures = 0
    for item in items:
        if item.get("type") != "text" or not any(
            intersect_area(item.get("bbox_pdf", []), rect) > 0 for rect in formula_rects
        ):
            cleaned_items.append(item)
            continue
        result = text_mod.region_text_ordered_excluding(
            page, item["bbox_pdf"], formula_rects, gutter_mid,
        )
        if result is None:
            failures += 1
            cleaned_items.append(item)
            continue
        cleaned, excluded_chars = result
        if excluded_chars == 0:
            cleaned_items.append(item)
            continue

        removed += 1
        cleaned = cleaned.strip()
        if len(cleaned) < 3:
            continue
        updated = dict(item)
        updated["text"] = cleaned
        content_type = updated.get("content_type")
        if isinstance(content_type, classify.ContentType):
            features = classify.extract_features(
                cleaned, updated["bbox_pdf"], page_num - 1,
                page_width, page_height, "text",
            )
            updated["markdown"] = classify.format_region(features, content_type)
        else:
            updated["markdown"] = cleaned
        cleaned_items.append(updated)
    return cleaned_items, removed, failures


def _matches_title_candidate(raw: str, rect: list[float], candidate: dict | None) -> bool:
    if not candidate:
        return False
    raw_key = _dedup_text_key(raw)
    title_key = _dedup_text_key(candidate.get("text", ""))
    if len(raw_key) < 4 or not (raw_key in title_key or title_key in raw_key):
        return False
    overlap = overlaps_any(rect, [candidate["bbox_pdf"]], thr=0.6)
    return overlap


_VENUE_STOP = ("UNIVERSITY", "PRESS", "DEPARTMENT", "INSTITUTE", "OXFORD",
               "LIBRARY", "CATALOGUING", "ISBN", "SCHOOL", "ACADEMY", "COLLEGE")


def _title_candidates_from_page(page, page_num: int = 1) -> list[dict]:
    """Collect title candidates with font evidence from the native text layer."""
    out: list[dict] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        spans = [span for line in block.get("lines", []) for span in line.get("spans", [])]
        text = " ".join(
            "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            for line in block.get("lines", [])
        ).strip()
        if not text or len(text) > 160:
            continue
        bbox = list(block["bbox"])
        if bbox[1] > page.rect.height * 0.40:
            continue
        font_size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
        boilerplate = bool(re.search(r"\b(Vol\.?|No\.?|ISSN|JOURNAL|UNIVERSITIES)\b", text, re.IGNORECASE))
        score = font_size * 4 + min(len(text), 80) * 0.08 - bbox[1] * 0.015 - (25 if boilerplate else 0)
        out.append({"page": page_num, "text": text, "bbox_pdf": bbox, "font_size": font_size, "score": score})
    return out


def _native_author_line(page, title: dict) -> str:
    """Select the short native text line immediately below a chosen article title."""
    title_bottom = title["bbox_pdf"][3]
    candidates: list[tuple[float, str]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        bbox = block["bbox"]
        if bbox[1] < title_bottom or bbox[1] > title_bottom + page.rect.height * 0.12:
            continue
        text = " ".join(
            "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            for line in block.get("lines", [])
        ).strip()
        if not text or len(text) > 160:
            continue
        if any(kw.lower() in text.lower() for kw in ("university", "department", "institute", "大学", "学院", "实验室")):
            continue
        candidates.append((bbox[1] - title_bottom, re.sub(r"\s+", " ", text)))
    return min(candidates, default=(0.0, ""), key=lambda item: item[0])[1]


def _normalize_author_line(raw: str) -> str:
    """Normalize author metadata without leaking affiliation superscripts."""
    text = re.split(r"\s*\(", str(raw or ""), maxsplit=1)[0].strip()
    if not re.search(r"[\u4e00-\u9fff]", text):
        return re.sub(r"\s+", " ", text).strip()
    if not re.search(r"[，,;；、]", text):
        text = re.sub(r"[0-9!＊*†‡]+", "", text)
        return re.sub(r"\s+", " ", text).strip(" ，,;；、")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    names: list[str] = []
    for segment in re.split(r"[，,;；、]+", text):
        names.extend(re.findall(r"[\u4e00-\u9fff]{2,}", segment))
    return " ".join(names) if names else re.sub(r"\s+", " ", text).strip()


def _best_native_title(doc, limit: int = 6) -> dict | None:
    candidates = []
    for index in range(min(limit, len(doc))):
        candidates.extend(_title_candidates_from_page(doc[index], index + 1))
    primary = max(candidates, key=lambda item: item["score"], default=None)
    if primary is None:
        return None
    same_page = sorted(
        (candidate for candidate in candidates if candidate["page"] == primary["page"]
         and candidate["bbox_pdf"][1] >= primary["bbox_pdf"][3]),
        key=lambda item: item["bbox_pdf"][1],
    )
    if same_page:
        following = same_page[0]
        gap = following["bbox_pdf"][1] - primary["bbox_pdf"][3]
        size_ratio = following["font_size"] / max(primary["font_size"], 1.0)
        primary_center = (primary["bbox_pdf"][0] + primary["bbox_pdf"][2]) / 2
        following_center = (following["bbox_pdf"][0] + following["bbox_pdf"][2]) / 2
        subtitle_marker = bool(re.match(r"\s*[-—－]+", following["text"]))
        continued_title = primary["text"].rstrip().endswith((":", "："))
        min_size_ratio = 0.6 if subtitle_marker else 0.75
        if gap <= doc[primary["page"] - 1].rect.height * 0.06 and size_ratio >= min_size_ratio \
                and abs(primary_center - following_center) <= doc[primary["page"] - 1].rect.width * 0.12 \
                and (subtitle_marker or continued_title or size_ratio >= 0.9):
            primary = {
                **primary,
                "text": f'{primary["text"].rstrip()} {following["text"].strip()}',
                "bbox_pdf": [
                    min(primary["bbox_pdf"][0], following["bbox_pdf"][0]),
                    primary["bbox_pdf"][1],
                    max(primary["bbox_pdf"][2], following["bbox_pdf"][2]),
                    following["bbox_pdf"][3],
                ],
            }
    return primary


def _extract_metadata(pages_items: list[list[dict]], doc=None) -> dict:
    """跨前 6 页提取元数据. 标题在标题页, 作者用全大写短行启发式."""
    meta = {"title": "", "authors": "", "year": "", "venue": "", "abstract": "", "keywords": ""}
    flat = [it for pg in pages_items[:6] for it in pg]
    title = None
    if doc is not None and len(doc):
        candidate = _best_native_title(doc)
        if candidate:
            title = {
                "page": candidate["page"], "text": candidate["text"],
                "bbox_pdf": candidate["bbox_pdf"], "content_type": classify.ContentType.TITLE,
            }
    if title is None:
        title = next((i for i in flat if i.get("content_type") in (classify.ContentType.TITLE, "TITLE")), None)
    if title:
        meta["title"] = re.sub(r"\s+", " ", str(title["text"]).strip().lstrip("# ")).strip()
        title_page = title["page"]
        if doc is not None and 1 <= title_page <= len(doc):
            meta["authors"] = _normalize_author_line(_native_author_line(doc[title_page - 1], title))
        author_cands = []
        for it in (x for x in flat if x["page"] == title_page):
            t = str(it.get("text", "")).strip()
            if not t:
                continue
            ct = it.get("content_type")
            if ct == classify.ContentType.AUTHOR:
                # 过滤非作者名: DOI / 机构 (研究所/大学等) / 脚注 (注./收稿/基金) / 长文本
                if (len(t) <= 120
                        and "DOI" not in t
                        and "10.7498" not in t
                        and not any(kw in t for kw in ("研究所", "大学", "学院", "实验室",
                                                       "University", "Institute", "Department", "Hospital"))
                        and not t.lstrip().startswith(("注", "收稿", "基金", "Received", "©", "(", "("))):
                    author_cands.append(t)
            elif ct == classify.ContentType.BODY and re.fullmatch(r"[A-Z.\-'\s]+", t) \
                    and t.isupper() and 3 <= len(t) <= 60 and not any(w in t for w in _VENUE_STOP):
                author_cands.append(t)
        seen: set[str] = set()
        uniq: list[str] = []
        for a in author_cands:
            if a not in seen:
                seen.add(a)
                uniq.append(a)
        if not meta["authors"]:
            meta["authors"] = " / ".join(uniq[:6])
    abstract = next((i for i in flat if i.get("content_type") == classify.ContentType.ABSTRACT), None)
    if abstract:
        meta["abstract"] = str(abstract["text"]).strip()
    keywords = next((i for i in flat if i.get("content_type") == classify.ContentType.KEYWORDS), None)
    if keywords:
        meta["keywords"] = str(keywords["text"]).strip()
    all_text = " ".join(str(i.get("text", "")) for i in flat)
    m = re.search(r"\b(19|20)\d{2}\b", all_text)
    if m:
        meta["year"] = m.group(0)
    return meta


@_offline_guard
def convert_pdf(
    pdf_path: str,
    output_dir: str,
    *,
    lang: str = "en",
    dpi: int = 220,
    image_dpi: int = 200,
    formula_dpi: int = 300,
    do_ocr: bool = True,
    keep_margins: bool = True,
    max_pages: int | None = None,
    formula_engine: str = "auto",
    use_table_model: bool = True,
    merge_policy: str = MERGE_EXPAND,
    layout_model_path: str | os.PathLike | None = None,
    layout_model_sha256: str | None = None,
    offline: bool = True,
    isolate: bool = True,
    resource_limits: ConversionLimits | dict | None = None,
) -> dict:
    limits = ConversionLimits.coerce(resource_limits)
    if isolate:
        return run_isolated_conversion(
            {
                "pdf_path": str(pdf_path),
                "output_dir": str(output_dir),
                "lang": lang,
                "dpi": dpi,
                "image_dpi": image_dpi,
                "formula_dpi": formula_dpi,
                "do_ocr": do_ocr,
                "keep_margins": keep_margins,
                "max_pages": max_pages,
                "formula_engine": formula_engine,
                "use_table_model": use_table_model,
                "merge_policy": merge_policy,
                "layout_model_path": str(layout_model_path) if layout_model_path is not None else None,
                "layout_model_sha256": layout_model_sha256,
                "offline": offline,
            },
            limits,
        )

    pdf_path = os.path.abspath(pdf_path)
    output_dir = os.path.abspath(output_dir)
    limits.validate_input(
        pdf_path, dpi=dpi, image_dpi=image_dpi, formula_dpi=formula_dpi,
        max_pages=max_pages,
    )
    detector_is_builtin = getattr(layout_mod.detect_layout, "__module__", None) == layout_mod.__name__
    if layout_model_path is not None or detector_is_builtin:
        model_info = preflight(
            layout_model_path, layout_model_sha256=layout_model_sha256,
            use_table_model=use_table_model, do_ocr=do_ocr,
            formula_engine=formula_engine, strict=True,
        )
    else:
        model_info = {
            "layout": {"name": "injected_layout_detector", "path": None, "available": True},
            "ocr": ocr_mod.adapter_status() if do_ocr else {"available": False, "disabled": True},
            "table": table_model.adapter_status() if use_table_model else {"available": False, "disabled": True},
            "formula": (
                formulas.FormulaModel.checkpoint_status()
                if formula_engine != "rapidocr"
                else {"available": False, "disabled": True}
            ),
            "warnings": [],
        }
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    t0 = time.time()

    doc = fitz.open(pdf_path)
    n_pages = len(doc) if max_pages is None else min(max_pages, len(doc))
    page_rects = [doc[i].rect for i in range(n_pages)]
    page_heights = {i + 1: doc[i].rect.height for i in range(n_pages)}
    profile = pdf_profile.profile_pdf(pdf_path)  # 预检 PDF 类型 (原生/扫描/混合)
    native_title = None
    if n_pages:
        native_title = _best_native_title(doc)

    # ── 1. YOLO 版面 ──
    all_regions = layout_mod.detect_layout(
        pdf_path, max_pages=n_pages, model_path=layout_model_path,
        model_sha256=layout_model_sha256,
    )
    limits.validate_regions(all_regions)

    # ── 1.5 无框表候选 (YOLO 漏检补丁): 原生文字网格 → 几何阶梯验证 ──
    for pno in range(n_pages):
        yolo_tables = [r["bbox_pdf"] for r in all_regions[pno] if r["visual_class"] == "table"]
        text_cands: list[list[float]] = []
        for cand in tables_mod.detect_text_table_candidates(doc[pno]):
            # 与 YOLO 表区或已加入的文本候选重叠 → 跳过 (互去重, 防重复处理)
            if overlaps_any(cand, yolo_tables) or overlaps_any(cand, text_cands):
                continue
            text_cands.append(cand)
            all_regions[pno].append({
                "page": pno + 1, "bbox_pdf": cand,
                "visual_class": "table", "confidence": None, "detector": "text",
            })
    # ── 2. 逐页提取元素 ──
    elements_by_page: list[list[dict]] = []
    page_gutters: list[float | None] = []
    stats = {
        "images": 0, "tables": 0, "table_images": 0, "formulas": 0,
        "formula_uncertain": 0, "formula_fallback_images": 0, "text_regions": 0,
        "ocr_pages": 0, "table_geometry": 0, "table_model": 0, "table_merged": 0,
        "visual_reclassified": 0, "visual_fallbacks": 0,
        "artifacts_suppressed": 0, "formula_rejected": 0,
        "inline_formulas": 0, "formula_multiscale_recovered": 0,
        "formula_text_duplicates_removed": 0,
        "formula_text_duplicates_remaining": 0,
    }
    formula_detected_anywhere = False
    h1_used = False
    # 公式门控: YOLO formula 区域少 (< MIN_PIX2TEX_FORMULAS) → 跳过 pix2tex (省 ~27s 模型加载),
    # 直接走 RapidOCR + 符号映射兜底。pix2tex 仅在公式多的文档才值得加载。
    yolo_formulas = sum(
        1 for pr in all_regions for r in pr if r["visual_class"] == "formula"
    )
    use_formula_model = _use_formula_model(
        formula_engine, detected_formulas=yolo_formulas
    )

    for pno in range(n_pages):
        if time.time() - t0 > limits.max_runtime_seconds:
            raise ResourceLimitError(
                f"resource_limit:runtime_seconds — exceeded {limits.max_runtime_seconds}"
            )
        page = doc[pno]
        pw, ph = page_rects[pno].width, page_rects[pno].height
        items: list[dict] = []
        accepted_formula_rects: list[list[float]] = []
        page_drawings = None  # get_drawings 页级缓存 (懒加载, 防每候选重复整页解析)
        # 版面阅读顺序: 页内文字块栏感知重排 (双栏左读完再右栏)
        page_blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        gutter_mid = reading_order.page_gutter_mid(page_blocks)  # 块级栏距 (稳健)
        page_gutters.append(gutter_mid)

        page_regions = []
        for region in all_regions[pno]:
            if region.get("visual_class") == "table":
                splits = split_table_region_by_captions(doc[pno], region["bbox_pdf"])
                if len(splits) > 1:
                    for split in splits:
                        child = dict(region)
                        child["bbox_pdf"] = split
                        child["semantic_reason"] = "caption_split_table_container"
                        page_regions.append(child)
                    continue
            page_regions.append(region)
        for r in page_regions:
            rect = r["bbox_pdf"]
            vc = r["visual_class"]

            if vc in ("figure", "table"):
                if page_drawings is None:
                    page_drawings = page.get_drawings()
                decision = visual.analyze_visual_region(page, rect, vc, drawings=page_drawings)
                semantic = decision["semantic_class"]
                if semantic != vc:
                    stats["visual_reclassified"] += 1
                r["detector_class"] = r.get("detector_class", vc)
                r["semantic_class"] = semantic
                r["semantic_reason"] = decision["reason"]
                r["evidence"] = decision["evidence"]
                if decision.get("caption"):
                    r["caption"] = decision["caption"]
                if semantic == "artifact":
                    stats["artifacts_suppressed"] += 1
                    continue
                vc = "figure" if semantic == "image" else semantic

            if vc == "figure":
                n = stats["images"] + 1
                rel = text_mod.save_image(page, rect, images_dir, f"page{pno+1:03d}_figure_{n:03d}.png", dpi=image_dpi)
                if rel:
                    stats["images"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "img", n), "page": pno + 1, "type": "image",
                        "bbox_pdf": rect, "text": "", "content_type": None,
                        "markdown": f"![figure]({rel})", "confidence": r.get("confidence"),
                        "detector_class": r.get("detector_class", "figure"),
                        "semantic_reason": r.get("semantic_reason", "detector_figure"),
                        "evidence": r.get("evidence", {}),
                    })
                # 图片内嵌原生文字不能丢 (半题名页/带文字插图), 与文本区域去重
                raw = text_mod.region_text(page, rect)
                if raw and len(raw) > 5 and not _text_already_present(items, raw):
                    items.append({
                        "id": _item_id(pno + 1, "figtxt", n), "page": pno + 1, "type": "text",
                        "bbox_pdf": rect, "text": raw, "content_type": classify.ContentType.BODY,
                        "markdown": raw, "confidence": None,
                    })
                continue

            if vc == "table":
                min_q = 0.75 if r.get("detector") == "text" else 0.0
                if r.get("semantic_reason") == "raster_table_candidate":
                    min_q = max(min_q, 0.85)
                if page_drawings is None:
                    page_drawings = page.get_drawings()
                frag = tables_mod.recognize_table(
                    page, rect,
                    dpi=dpi, do_ocr=do_ocr, use_model=use_table_model, merge_policy=merge_policy,
                    drawings=page_drawings,
                )
                if frag is not None and min_q and (frag.get("structure_quality") or 0) < min_q:
                    frag = None  # 文字网格候选: 质量未达高门槛 → 按散文/图片兜底
                if frag is not None and min_q and tables_mod._prose_like_table(frag):
                    frag = None  # 双栏散文被误建成表 → 拒绝, 回退为文本
                if frag is None and r.get("detector") == "text":
                    # 文本网格候选被拒 (散文/质量不足) → 恢复为正文文本, 不存表格图片
                    raw = text_mod.region_text(page, rect)
                    if raw and len(raw) >= 3 and not _text_already_present(items, raw):
                        stats["text_regions"] += 1
                        items.append({
                            "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                            "type": "text", "bbox_pdf": rect, "text": raw,
                            "content_type": classify.ContentType.BODY, "markdown": raw, "confidence": None,
                        })
                    continue
                if frag is not None:
                    stats["tables"] += 1
                    src = frag.get("source", "")
                    if src in ("geometry_native", "geometry_ocr"):
                        stats["table_geometry"] += 1
                    elif src == "structure_model":
                        stats["table_model"] += 1
                    item = {
                        "id": _item_id(pno + 1, "tab", stats["tables"]), "page": pno + 1,
                        "type": "table", "bbox_pdf": rect, "text": frag.get("text", ""),
                        "content_type": None, "markdown": frag["markdown"],
                        "confidence": frag.get("confidence"),
                        "detector_class": r.get("detector_class", "table"),
                        "semantic_reason": r.get("semantic_reason", "table_evidence"),
                        "evidence": r.get("evidence", {}),
                    }
                    for extra in ("html", "structure_quality", "cell_confidences", "source"):
                        if frag.get(extra) is not None:
                            item[extra] = frag[extra]
                    items.append(item)
                    continue
                raw = text_mod.region_text(page, rect)
                if raw and len(raw) >= 3 and not tables_mod.looks_like_table_data(raw) \
                        and not _text_already_present(items, raw):
                    # YOLO 把散文误判为 table → 恢复为文本
                    stats["text_regions"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                        "type": "text", "bbox_pdf": rect, "text": raw,
                        "content_type": classify.ContentType.BODY, "markdown": raw, "confidence": None,
                    })
                    continue
                # 无可靠结构证据时保留视觉内容, 但不伪装成已确认的表格。
                n = stats["images"] + 1
                rel = text_mod.save_image(page, rect, images_dir, f"page{pno+1:03d}_visual_{n:03d}.png", dpi=image_dpi)
                if rel:
                    stats["images"] += 1
                    stats["visual_fallbacks"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "img", n), "page": pno + 1,
                        "type": "image", "bbox_pdf": rect, "text": "", "content_type": None,
                        "markdown": f"![visual]({rel})", "confidence": r.get("confidence"),
                        "detector_class": r.get("detector_class", "table"),
                        "semantic_reason": "table_unconfirmed",
                        "evidence": r.get("evidence", {}),
                    })
                continue

            if vc == "formula":
                formula_detected_anywhere = True
                # 图注/长文被误判为 formula → 直接用原生文字, 不 OCR 糟蹋
                native = text_mod.region_text(page, rect)
                # Split a genuine stacked equation group before applying the
                # single-region prose/length gate. A multi-line native text
                # block can exceed the 300-character guard while each
                # displayed equation remains a valid candidate.
                formula_parts = formulas.formula_region_parts(page, rect, native)
                if len(formula_parts) == 1 and native and not formulas.is_formula_candidate(native):
                    stats["formula_rejected"] += 1
                    stats["text_regions"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                        "type": "text", "bbox_pdf": rect, "text": native,
                        "content_type": classify.ContentType.BODY, "markdown": native, "confidence": None,
                    })
                    continue
                represented_formula_rects: list[list[float]] = []
                for formula_rect in formula_parts:
                    native_latex = formulas.native_formula_latex(
                        text_mod.region_text(page, formula_rect)
                    )
                    if native_latex:
                        latex, conf, engine = native_latex, 0.92, "native"
                    else:
                        latex, conf, engine = formulas.ocr_formula_latex(
                            page, formula_rect, dpi=formula_dpi, use_model=use_formula_model
                        )
                        if (
                            use_formula_model
                            and (not latex or not formulas.is_real_formula(latex))
                            and formula_dpi != 200
                        ):
                            retry_latex, retry_conf, retry_engine = formulas.ocr_formula_latex(
                                page, formula_rect, dpi=200, use_model=True
                            )
                            if retry_latex and formulas.is_real_formula(retry_latex):
                                latex, conf, engine = retry_latex, retry_conf, retry_engine
                                stats["formula_multiscale_recovered"] += 1
                    if not latex or not formulas.is_real_formula(latex):
                        if latex:
                            stats["formula_rejected"] += 1
                        stats["formula_fallback_images"] += 1
                        n = stats["images"] + 1
                        rel = text_mod.save_image(
                            page, formula_rect, images_dir,
                            f"page{pno+1:03d}_formula_{n:03d}.png", dpi=image_dpi,
                        )
                        if rel:
                            stats["images"] += 1
                            items.append({
                                "id": _item_id(pno + 1, "fimg", n), "page": pno + 1,
                                "type": "image", "bbox_pdf": formula_rect, "text": "",
                                "content_type": None, "markdown": f"![formula]({rel})",
                                "confidence": conf,
                            })
                            represented_formula_rects.append(formula_rect)
                        continue
                    stats["formulas"] += 1
                    if engine != "pix2tex" and conf < 0.85:
                        stats["formula_uncertain"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "fml", stats["formulas"]), "page": pno + 1,
                        "type": "formula", "bbox_pdf": formula_rect, "text": latex,
                        "content_type": None, "markdown": latex, "confidence": conf,
                        "engine": engine,
                    })
                    represented_formula_rects.append(formula_rect)
                if len(represented_formula_rects) == len(formula_parts):
                    accepted_formula_rects.append(rect)
                else:
                    accepted_formula_rects.extend(represented_formula_rects)
                continue

            if _is_textlike(vc):
                raw = text_mod.region_text_ordered(page, rect, gutter_mid)
                if not raw or len(raw) < 3:
                    continue
                if _text_already_present(items, raw):
                    continue  # 与图注/相邻区域去重
                feat = classify.extract_features(raw, rect, pno, pw, ph, vc)
                if native_title and pno + 1 == native_title["page"] \
                        and _matches_title_candidate(raw, rect, native_title) and not h1_used:
                    ct = classify.ContentType.TITLE
                    h1_used = True
                else:
                    ct = classify.classify(feat)
                md = classify.format_region(feat, ct)
                stats["text_regions"] += 1
                items.append({
                    "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                    "type": "text", "bbox_pdf": rect, "text": raw, "content_type": ct,
                    "markdown": md, "confidence": None,
                })

        # ── OCR 兜底: 文字层空了但 YOLO 认为有文本内容 → 整页 OCR ──
        if do_ocr:
            text_items = [i for i in items if i["type"] == "text"]
            if not text_items and any(_is_textlike(r["visual_class"]) for r in all_regions[pno]):
                try:
                    lines = ocr_mod.ocr_region(page, [0, 0, pw, ph], dpi=dpi)
                    joined = "\n".join(t for t, _ in lines if t)
                    if joined.strip():
                        stats["ocr_pages"] += 1
                        items.append({
                            "id": _item_id(pno + 1, "ocr", 1), "page": pno + 1,
                            "type": "ocr_text", "bbox_pdf": [0, 0, pw, ph],
                            "text": joined, "content_type": None, "markdown": joined, "confidence": None,
                        })
                except Exception:
                    pass

        # ── 空隙检测: 文字层不可见的显示公式 (老式 LaTeX Type3 字形) ──
        if do_ocr and pno >= 3:
            excluded = [r["bbox_pdf"] for r in all_regions[pno]
                        if r["visual_class"] in ("figure", "table", "formula")]
            for grect in formulas.find_equation_gaps(page, excluded):
                if not formulas.has_ink(page, grect):
                    continue  # 纯空白段落间隙, 无墨迹
                # 空隙可能含多条堆叠公式 → 按墨迹行拆分, 每条单独 OCR
                for line_rect in formulas.split_ink_lines(page, grect):
                    g_latex, g_conf, g_engine = formulas.ocr_formula_latex(
                        page, line_rect, dpi=formula_dpi, use_model=use_formula_model
                    )
                    if g_latex and formulas.is_real_formula(g_latex):
                        stats["formulas"] += 1
                        if g_engine != "pix2tex" and g_conf < 0.85:
                            stats["formula_uncertain"] += 1
                        items.append({
                            "id": _item_id(pno + 1, "fml", stats["formulas"]), "page": pno + 1,
                            "type": "formula", "bbox_pdf": line_rect, "text": g_latex,
                            "content_type": None, "markdown": g_latex, "confidence": g_conf,
                            "engine": g_engine,
                        })

                        accepted_formula_rects.append(line_rect)

        items, formula_duplicates_removed, formula_cleanup_failures = (
            _remove_formula_text_duplicates(
                page, items, accepted_formula_rects, gutter_mid=gutter_mid,
                page_num=pno + 1, page_width=pw, page_height=ph,
            )
        )
        stats["formula_text_duplicates_removed"] += formula_duplicates_removed
        stats["formula_text_duplicates_remaining"] += formula_cleanup_failures

        items, removed = _deduplicate_page_items(items)
        for item in items:
            if item.get("type") not in {"text", "ocr_text"}:
                continue
            formatted, inline_count = formulas.format_inline_formulas(item.get("markdown", ""))
            item["markdown"] = formatted
            stats["inline_formulas"] += inline_count
        stats.setdefault("text_duplicates_removed", 0)
        stats["text_duplicates_removed"] += removed
        elements_by_page.append(items)
        limits.validate_output(output_dir)

    # ── 2.5 跨页续表合并 (保守规则: 前页靠底 + 后页靠顶 + 列结构一致) ──
    stats["table_merged"] = _merge_cross_page_tables(elements_by_page, page_heights)
    stats["tables"] -= stats["table_merged"]  # 合并后表数量减少

    # ── 3. 元数据 (前 6 页) ──
    meta = _extract_metadata(elements_by_page, doc)

    # ── 4. 页眉页脚 (跨页重复, 基于文字层, 每页用自己的高度) ──
    if keep_margins:
        top_set, bottom_set = _repeated_margins(doc, n_pages)
        for idx, items in enumerate(elements_by_page):
            h = doc[idx].rect.height
            band = h * 0.12
            for it in items:
                if it.get("type") != "text":
                    continue
                key = _norm2(it.get("text", ""))
                if it["bbox_pdf"][1] <= band and key in top_set:
                    it["type"] = "header"
                elif it["bbox_pdf"][3] >= h - band and key in bottom_set:
                    it["type"] = "footer"

    # ── 5. 阅读顺序 + 组装 ──
    ordered_pages = []
    for pno, items in enumerate(elements_by_page):
        # 页眉钉页首, 页脚钉页尾, 覆盖列排序
        headers = [it for it in items if it["type"] == "header"]
        footers = [it for it in items if it["type"] == "footer"]
        rest = [it for it in items if it["type"] not in ("header", "footer")]
        ordered_rest = order_mod.order_page_elements(
            rest,
            page_width=page_rects[pno].width,
            gutter_mid=page_gutters[pno],
        )
        if pno == 0:
            # Keep the selected article title as the document entry point, but
            # let every other front-page block follow geometric reading order.
            title_items = [
                item for item in ordered_rest
                if item.get("content_type") == classify.ContentType.TITLE
            ]
            ordered_rest = title_items + [item for item in ordered_rest if item not in title_items]
        ordered = headers + ordered_rest + footers
        for idx, it in enumerate(ordered, 1):
            it["reading_order"] = idx
        ordered_pages.append({"page": pno + 1, "items": ordered})

    # ── 6. 文字不丢失 ──
    native_texts = [doc[i].get_text("text") for i in range(n_pages)]
    page_md_texts = [
        "\n".join(normalize.item_to_markdown(it) for it in p["items"]) for p in ordered_pages
    ]
    coverage = textloss.coverage_report(native_texts, page_md_texts)
    coverage_flags = {c["flag"] for c in coverage}
    quality_status = (
        "suspect" if "suspect" in coverage_flags
        else "unverifiable" if "unverifiable" in coverage_flags
        else "ok"
    )
    quality = {
        "status": quality_status,
        "duplicate_text_count": sum(c.get("duplicate_lines", 0) for c in coverage),
        "suspect_pages": [c["page"] for c in coverage if c["flag"] != "ok"],
        "visual_reclassified": stats["visual_reclassified"],
        "visual_fallbacks": stats["visual_fallbacks"],
        "artifacts_suppressed": stats["artifacts_suppressed"],
        "formula_rejected": stats["formula_rejected"],
        "text_duplicates_removed": stats.get("text_duplicates_removed", 0),
        "formula_text_duplicates_removed": stats["formula_text_duplicates_removed"],
        "formula_text_duplicates_remaining": stats["formula_text_duplicates_remaining"],
    }

    # ── 7. 最终 Markdown ──
    markdown = normalize.build_markdown(meta, ordered_pages)
    md_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(pdf_path))[0]}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    # ── 8. 侧车 ──
    formula_detected = formula_detected_anywhere
    for _p in ordered_pages:
        for _it in _p["items"]:
            _ct = _it.get("content_type")
            if _ct is not None:
                _it["content_type"] = _ct.name  # ContentType 枚举 → JSON 可序列化字符串
    sidecar.write_sidecar(output_dir, {
        "pdf": pdf_path,
        "pages": n_pages,
        "pdf_profile": profile,
        "meta": meta,
        "stats": stats,
        "formula_detected": formula_detected,
        "coverage": coverage,
        "quality": quality,
        "models": model_info,
        "offline": offline,
        "elements": [{ "page": p["page"], "items": p["items"] } for p in ordered_pages],
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    limits.validate_output(output_dir)

    doc.close()
    return {
        "markdown_path": md_path,
        "markdown": markdown,
        "output_dir": output_dir,
        "elements": [{"page": p["page"], "items": p["items"]} for p in ordered_pages],
        "pdf_profile": profile,
        "stats": stats,
        "coverage": coverage,
        "quality": quality,
        "models": model_info,
        "offline": offline,
        "meta": meta,
        "formula_detected": formula_detected,
        "elapsed_s": round(time.time() - t0, 1),
    }


def _merge_cross_page_tables(elements_by_page: list[list[dict]], page_heights: dict) -> int:
    """跨页续表合并: 前一页靠底 + 后一页靠顶 + 列结构一致 → 合并为一个表格.

    保守规则防误并: 只合并「前一页底部的表」与「后一页顶部的表」且列数一致。
    返回合并次数。
    """
    merged_count = 0
    for pno in range(1, len(elements_by_page)):
        prev_items = elements_by_page[pno - 1]
        curr_items = elements_by_page[pno]
        prev_h = page_heights[pno]
        curr_h = page_heights[pno + 1]
        for pt in prev_items:
            if pt["type"] != "table" or pt["bbox_pdf"][3] < prev_h * 0.85:
                continue
            for ct in list(curr_items):
                if ct["type"] != "table" or ct["bbox_pdf"][1] > curr_h * 0.15:
                    continue
                merged = tables_mod.merge_table_items(pt, ct)
                if merged is not None:
                    pt.update(merged)
                    curr_items.remove(ct)
                    merged_count += 1
                    break
    return merged_count


def _type_priority(item: dict) -> int:
    return {"image": 9, "table": 10, "table_image": 10, "formula": 11, "header": 12, "footer": 12, "ocr_text": 13}.get(
        item["type"], 50
    )
