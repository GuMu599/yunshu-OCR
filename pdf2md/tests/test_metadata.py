"""Document metadata is selected from page evidence, not detector order."""

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.pipeline import _extract_metadata, _normalize_author_line  # noqa: E402


def test_larger_article_title_beats_journal_running_header():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((100, 45), "CHEMICAL JOURNAL OF EXAMPLES", fontsize=9)
    page.insert_text((150, 130), "Controllable Reduction of Graphene Oxide", fontsize=20)
    items = [[
        {"page": 1, "type": "text", "content_type": "TITLE", "text": "CHEMICAL JOURNAL OF EXAMPLES", "bbox_pdf": [100, 30, 500, 55]},
        {"page": 1, "type": "text", "content_type": "BODY", "text": "Controllable Reduction of Graphene Oxide", "bbox_pdf": [140, 110, 520, 145]},
    ]]

    meta = _extract_metadata(items, doc)

    assert meta["title"] == "Controllable Reduction of Graphene Oxide"
    doc.close()


def test_author_line_is_taken_from_native_block_below_title():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((150, 130), "Graphene Oxide Study", fontsize=20)
    page.insert_text((170, 175), "Alice Zhang 1, Bob Li 2", fontsize=12)
    page.insert_text((100, 205), "1 Department of Materials, Example University", fontsize=9)

    meta = _extract_metadata([], doc)

    assert meta["authors"] == "Alice Zhang 1, Bob Li 2"
    doc.close()


def test_title_can_start_on_a_later_front_matter_page():
    doc = fitz.open()
    doc.new_page(width=600, height=840)
    page = doc.new_page(width=600, height=840)
    page.insert_text((150, 130), "Later Article Title", fontsize=20)
    page.insert_text((170, 175), "Alice Zhang", fontsize=12)
    meta = _extract_metadata([[], []], doc)
    assert meta["title"] == "Later Article Title"
    doc.close()


def test_centered_subtitle_is_merged_before_author_selection():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((150, 120), "Original Problem Teaching:", fontsize=20)
    page.insert_text((170, 155), "A New View of Physics Education", fontsize=18)
    page.insert_text((260, 200), "Xing Hongjun", fontsize=12)

    meta = _extract_metadata([], doc)

    assert meta["title"] == "Original Problem Teaching: A New View of Physics Education"
    assert meta["authors"] == "Xing Hongjun"
    doc.close()


def test_dash_prefixed_subtitle_is_not_selected_as_author():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((120, 120), "Asian Currency Cooperation", fontsize=20)
    page.insert_text((150, 155), "--- Evidence from SURADF", fontsize=18)
    page.insert_text((220, 200), "Peng Hongfeng", fontsize=12)

    meta = _extract_metadata([], doc)

    assert meta["title"] == "Asian Currency Cooperation --- Evidence from SURADF"
    assert meta["authors"] == "Peng Hongfeng"
    doc.close()


def test_chinese_author_line_removes_affiliation_markers_and_single_character_gaps():
    raw = "杨旭宇1，2，王贤保1 !，李 静1，杨 佳1，万 丽1，王敬超1 (1．湖北大学材料学院)"

    assert _normalize_author_line(raw) == "杨旭宇 王贤保 李静 杨佳 万丽 王敬超"
