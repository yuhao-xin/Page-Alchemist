"""Transform stage: every rule, its report counters and its escape hatches."""
from __future__ import annotations

import pytest

from page_alchemist.transform import (RETUNE_EMOJI, TransformOptions,
                                        pick_emoji, transform_document)


class TestTitleNormalisation:
    def test_brand_prefix_and_decor_stripped(self, transform_doc):
        transform_document(transform_doc, TransformOptions())
        assert transform_doc.pages[0].title == "Ultimate Notion Template"

    def test_cjk_title_untouched(self, transform_doc):
        transform_doc.pages[0].title = "我的付费模板库"
        transform_document(transform_doc, TransformOptions())
        assert transform_doc.pages[0].title == "我的付费模板库"

    def test_empty_result_keeps_original(self, transform_doc):
        transform_doc.pages[0].title = "【模板】"
        transform_document(transform_doc, TransformOptions())
        assert transform_doc.pages[0].title == "【模板】"

    def test_keep_titles_opt_out(self, transform_doc):
        transform_document(transform_doc, TransformOptions(normalize_titles=False))
        assert transform_doc.pages[0].title.startswith("📚")


class TestNoiseAndSynced:
    def test_noise_types_dropped(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        types_seq = [b.type for b in transform_doc.pages[0].blocks]
        for noise in ("table_of_contents", "breadcrumb", "ai_block",
                      "child_database"):
            assert noise not in types_seq
        assert report.dropped.get("table_of_contents") == 1

    def test_synced_block_unwrapped(self, transform_doc):
        transform_document(transform_doc, TransformOptions())
        blocks = transform_doc.pages[0].blocks
        assert not any(b.type == "synced_block" for b in blocks)
        assert any(b.plain_text() == "synced body" for b in blocks)

    def test_keep_noise_opt_out(self, transform_doc):
        transform_document(transform_doc,
                           TransformOptions(drop_noise=False))
        types_seq = [b.type for b in transform_doc.pages[0].blocks]
        assert "table_of_contents" in types_seq
        assert "synced_block" in types_seq


class TestColors:
    def test_all_colors_stripped(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        for b in transform_doc.pages[0].blocks:
            for rt in list(b.text) + list(b.caption):
                assert rt.color == "default"
        assert report.colors_stripped >= 2

    def test_keep_colors_opt_out(self, transform_doc):
        transform_document(transform_doc, TransformOptions(strip_colors=False))
        para = [b for b in transform_doc.pages[0].blocks
                if b.plain_text() == "Coloured text"][0]
        assert para.text[0].color == "red_background"


class TestIcons:
    def test_retune_replaces_emoji_and_url(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        assert transform_doc.pages[0].icon in RETUNE_EMOJI
        assert transform_doc.pages[0].icon != "🎁"
        child = transform_doc.pages[0].children[0]
        assert child.icon in RETUNE_EMOJI          # signed URL icon replaced
        assert report.icons_retuned == 2

    def test_keep_mode(self, transform_doc):
        transform_document(transform_doc, TransformOptions(icon_mode="keep"))
        assert transform_doc.pages[0].icon == "🎁"

    def test_none_mode(self, transform_doc):
        transform_document(transform_doc, TransformOptions(icon_mode="none"))
        assert transform_doc.pages[0].icon is None

    def test_pick_emoji_deterministic(self):
        assert pick_emoji("weekly-review") == pick_emoji("weekly-review")
        assert pick_emoji("weekly-review") in RETUNE_EMOJI

    def test_invalid_mode_rejected(self, transform_doc):
        with pytest.raises(ValueError, match="icon_mode"):
            transform_document(transform_doc, TransformOptions(icon_mode="bogus"))


class TestRelayout:
    def test_h1_demoted_everywhere(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        assert "heading_1" not in [b.type for b in transform_doc.pages[0].blocks]
        child_blocks = transform_doc.pages[0].children[0].blocks
        assert "heading_1" not in [b.type for b in child_blocks]
        assert report.h1_demoted == 2

    def test_keep_h1_opt_out(self, transform_doc):
        transform_document(transform_doc, TransformOptions(demote_h1=False))
        assert "heading_1" in [b.type for b in transform_doc.pages[0].blocks]

    def test_adjacent_duplicates_removed(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        same = [b for b in transform_doc.pages[0].blocks
                if b.plain_text() == "same"]
        assert len(same) == 1
        assert report.duplicates_removed == 1

    def test_non_adjacent_duplicates_kept(self, transform_doc):
        from page_alchemist.models import Block, RichText
        page = transform_doc.pages[0]
        page.blocks = [
            Block(type="paragraph", text=[RichText(text="dup")]),
            Block(type="heading_2", text=[RichText(text="mid")]),
            Block(type="paragraph", text=[RichText(text="dup")]),
        ]
        transform_document(transform_doc, TransformOptions(add_archive_card=False))
        assert sum(1 for b in page.blocks if b.plain_text() == "dup") == 2

    def test_empty_paragraph_dropped(self, transform_doc):
        transform_document(transform_doc, TransformOptions())
        assert not any(b.type == "paragraph" and not b.plain_text()
                       for b in transform_doc.pages[0].blocks)


class TestTableRowsSurvive:
    def test_table_row_not_dropped_as_empty(self, transform_doc):
        from page_alchemist.models import Block, RichText
        page = transform_doc.pages[0]
        page.blocks = [Block(type="table",
                             raw={"table": {"table_width": 2}},
                             children=[Block(
                                 type="table_row",
                                 cells=[[RichText(text="x")],
                                        [RichText(text="y")]])])]
        transform_document(transform_doc, TransformOptions())
        table = page.blocks[-1]
        assert table.type == "table"
        assert len(table.children) == 1


class TestArchiveCard:
    def test_card_prepended_with_provenance(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        card = transform_doc.pages[0].blocks[0]
        assert card.type == "callout"
        assert "notion.so" in card.plain_text()
        assert "引擎：api" in card.plain_text()
        assert "章节：" in card.plain_text()
        assert report.cards_added == 2

    def test_opt_out(self, transform_doc):
        transform_document(transform_doc, TransformOptions(add_archive_card=False))
        assert transform_doc.pages[0].blocks[0].type != "callout"


class TestReport:
    def test_summary_counts(self, transform_doc):
        report = transform_document(transform_doc, TransformOptions())
        text = report.summary()
        assert "blocks" in text and "dropped" in text and "icons retuned" in text
        # 12 page-level blocks in (11 root + 1 child); after dropping 6,
        # unwrapping the synced block (+1), de-duplicating (-1) and adding
        # 2 archive cards: 9 out
        assert report.blocks_in == 12
        assert report.blocks_out == 9

    def test_stats_recorded_on_document(self, transform_doc):
        transform_document(transform_doc, TransformOptions())
        assert "transform" in transform_doc.stats
