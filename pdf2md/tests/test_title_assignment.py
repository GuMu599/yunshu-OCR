"""Only the native article-title candidate becomes Markdown H1."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.pipeline import _matches_title_candidate  # noqa: E402


def test_region_matching_title_candidate_is_selected():
    title = {"text": "Controllable Reduction of Graphene Oxide", "bbox_pdf": [140, 110, 520, 145]}
    assert _matches_title_candidate("Controllable Reduction of Graphene Oxide", [138, 108, 522, 147], title)


def test_journal_header_does_not_match_article_title():
    title = {"text": "Controllable Reduction of Graphene Oxide", "bbox_pdf": [140, 110, 520, 145]}
    assert not _matches_title_candidate("CHEMICAL JOURNAL OF EXAMPLES", [100, 30, 500, 55], title)
