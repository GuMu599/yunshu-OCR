"""主编排: YOLO 版面 → 提取 → 分类 → 公式/表格/图片 → 排序+页眉页脚 → 规范 → 文字不丢失.

convert_pdf() 是唯一入口, 返回报告 dict。
"""

from __future__ import annotations

import os
import re
import time
from collections import Counter

import fitz

from . import classify, formulas, layout as layout_mod, normalize, ocr as ocr_mod, order as order_mod
from . import pdf_profile, reading_order, sidecar, tables as tables_mod, text as text_mod, textloss
from .geometry import overlaps_any
from .table_html import MERGE_EXPAND


MIN_PIX2TEX_FORMULAS = 3  # 公式门控: YOLO formula 区 < 该值 → 不加载 pix2tex


def _is_textlike(vc: str) -> bool:
    return vc in ("text", "title", "abstract", "list", "reference", "unknown")



def _item_id(page: int, kind: str, n: int) -> str:
    return f"p{page:03d}-{kind}-{n:03d}"


def _norm2(text) -> str:
    """规范化页眉文本: 去数字/空白/标点, 小写. 用于跨页重复匹配."""
    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
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


_VENUE_STOP = ("UNIVERSITY", "PRESS", "DEPARTMENT", "INSTITUTE", "OXFORD",
               "LIBRARY", "CATALOGUING", "ISBN", "SCHOOL", "ACADEMY", "COLLEGE")


def _extract_metadata(pages_items: list[list[dict]]) -> dict:
    """跨前 6 页提取元数据. 标题在标题页, 作者用全大写短行启发式."""
    meta = {"title": "", "authors": "", "year": "", "venue": "", "abstract": "", "keywords": ""}
    flat = [it for pg in pages_items[:6] for it in pg]
    title = next((i for i in flat if i.get("content_type") == classify.ContentType.TITLE), None)
    if title:
        meta["title"] = re.sub(r"\s+", " ", str(title["text"]).strip().lstrip("# ")).strip()
        title_page = title["page"]
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
) -> dict:
    pdf_path = os.path.abspath(pdf_path)
    output_dir = os.path.abspath(output_dir)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    t0 = time.time()

    doc = fitz.open(pdf_path)
    n_pages = len(doc) if max_pages is None else min(max_pages, len(doc))
    page_rects = [doc[i].rect for i in range(n_pages)]
    page_heights = {i + 1: doc[i].rect.height for i in range(n_pages)}
    profile = pdf_profile.profile_pdf(pdf_path)  # 预检 PDF 类型 (原生/扫描/混合)

    # ── 1. YOLO 版面 ──
    all_regions = layout_mod.detect_layout(pdf_path, max_pages=n_pages)

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
    stats = {
        "images": 0, "tables": 0, "table_images": 0, "formulas": 0,
        "formula_uncertain": 0, "formula_fallback_images": 0, "text_regions": 0,
        "ocr_pages": 0, "table_geometry": 0, "table_model": 0, "table_merged": 0,
    }
    formula_detected_anywhere = False
    h1_used = False
    # 公式门控: YOLO formula 区域少 (< MIN_PIX2TEX_FORMULAS) → 跳过 pix2tex (省 ~27s 模型加载),
    # 直接走 RapidOCR + 符号映射兜底。pix2tex 仅在公式多的文档才值得加载。
    if formula_engine == "pix2tex":
        use_formula_model = True
    elif formula_engine == "rapidocr":
        use_formula_model = False
    else:  # auto
        yolo_formulas = sum(
            1 for pr in all_regions for r in pr if r["visual_class"] == "formula"
        )
        use_formula_model = yolo_formulas >= MIN_PIX2TEX_FORMULAS

    for pno in range(n_pages):
        page = doc[pno]
        pw, ph = page_rects[pno].width, page_rects[pno].height
        items: list[dict] = []
        page_drawings = None  # get_drawings 页级缓存 (懒加载, 防每候选重复整页解析)
        # 版面阅读顺序: 页内文字块栏感知重排 (双栏左读完再右栏)
        page_blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        gutter_mid = reading_order.page_gutter_mid(page_blocks)  # 块级栏距 (稳健)

        for r in all_regions[pno]:
            rect = r["bbox_pdf"]
            vc = r["visual_class"]

            if vc == "figure":
                n = stats["images"] + 1
                rel = text_mod.save_image(page, rect, images_dir, f"page{pno+1:03d}_figure_{n:03d}.png", dpi=image_dpi)
                if rel:
                    stats["images"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "img", n), "page": pno + 1, "type": "image",
                        "bbox_pdf": rect, "text": "", "content_type": None,
                        "markdown": f"![figure]({rel})", "confidence": None,
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
                # 最后防线: 图片型表格 → 表格图片 + 标记
                n = stats["table_images"] + 1
                rel = text_mod.save_image(page, rect, images_dir, f"page{pno+1:03d}_table_{n:03d}.png", dpi=image_dpi)
                if rel:
                    stats["table_images"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "tabi", n), "page": pno + 1,
                        "type": "table_image", "bbox_pdf": rect, "text": "", "content_type": None,
                        "markdown": f"![table]({rel})\n{tables_mod.IMG_MARKER}", "confidence": None,
                    })
                continue

            if vc == "formula":
                formula_detected_anywhere = True
                # 图注/长文被误判为 formula → 直接用原生文字, 不 OCR 糟蹋
                native = text_mod.region_text(page, rect)
                if native and (len(native) > 120 or formulas.looks_like_caption(native)):
                    stats["text_regions"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                        "type": "text", "bbox_pdf": rect, "text": native,
                        "content_type": classify.ContentType.BODY, "markdown": native, "confidence": None,
                    })
                    continue
                latex, conf, engine = formulas.ocr_formula_latex(
                    page, rect, dpi=formula_dpi, use_model=use_formula_model
                )
                stats["formulas"] += 1
                if not latex:
                    stats["formula_fallback_images"] += 1
                    n = stats["images"] + 1
                    rel = text_mod.save_image(page, rect, images_dir, f"page{pno+1:03d}_formula_{n:03d}.png", dpi=image_dpi)
                    if rel:
                        stats["images"] += 1
                        items.append({
                            "id": _item_id(pno + 1, "fimg", n), "page": pno + 1, "type": "image",
                            "bbox_pdf": rect, "text": "", "content_type": None,
                            "markdown": f"![formula]({rel})", "confidence": conf,
                        })
                    continue
                # 假公式守卫: 无任何数学内容的 OCR 结果 → 降为正文 (如 YOLO 把标题误判为 formula)
                if not formulas.is_real_formula(latex):
                    stats["text_regions"] += 1
                    items.append({
                        "id": _item_id(pno + 1, "txt", stats["text_regions"]), "page": pno + 1,
                        "type": "text", "bbox_pdf": rect, "text": latex, "content_type": classify.ContentType.BODY,
                        "markdown": latex, "confidence": conf,
                    })
                    continue
                if engine != "pix2tex" and conf < 0.85:
                    stats["formula_uncertain"] += 1
                items.append({
                    "id": _item_id(pno + 1, "fml", stats["formulas"]), "page": pno + 1,
                    "type": "formula", "bbox_pdf": rect, "text": latex, "content_type": None,
                    "markdown": latex, "confidence": conf, "engine": engine,
                })
                continue

            if _is_textlike(vc):
                raw = text_mod.region_text_ordered(page, rect, gutter_mid)
                if not raw or len(raw) < 3:
                    continue
                if _text_already_present(items, raw):
                    continue  # 与图注/相邻区域去重
                feat = classify.extract_features(raw, rect, pno, pw, ph, vc)
                if pno <= 5 and feat.is_page_top and vc in ("title", "text") \
                        and classify.looks_like_title(feat) and not h1_used:
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

        elements_by_page.append(items)

    # ── 2.5 跨页续表合并 (保守规则: 前页靠底 + 后页靠顶 + 列结构一致) ──
    stats["table_merged"] = _merge_cross_page_tables(elements_by_page, page_heights)
    stats["tables"] -= stats["table_merged"]  # 合并后表数量减少

    # ── 3. 元数据 (前 6 页) ──
    meta = _extract_metadata(elements_by_page)

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
        if pno == 0:
            # 首页: 按 PAGE0 结构 (标题/摘要/正文) 分组, 组内用栏感知 rank (先左后右, 不再按 y 交错)
            page_rect = fitz.Rect(0, 0, page_rects[pno].width, page_heights[pno + 1])
            rank0 = reading_order.reading_order_rank(
                [i["bbox_pdf"] for i in rest], page_rect, gutter_mid=gutter_mid
            )
            ordered_rest = sorted(rest, key=lambda i: (
                classify.PAGE0_ORDER.get(i.get("content_type"), _type_priority(i)),
                rank0.get(id(i["bbox_pdf"]), 0),
            ))
        else:
            ordered_rest = order_mod.order_page_elements(rest, page_width=page_rects[pno].width,
                                                       gutter_mid=gutter_mid)
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
        "elements": [{ "page": p["page"], "items": p["items"] } for p in ordered_pages],
        "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    })

    doc.close()
    return {
        "markdown_path": md_path,
        "markdown": markdown,
        "output_dir": output_dir,
        "elements": [{"page": p["page"], "items": p["items"]} for p in ordered_pages],
        "pdf_profile": profile,
        "stats": stats,
        "coverage": coverage,
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
