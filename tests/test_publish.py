"""Publish stage: dry-run planning, payload shape, chunking, resume, state."""
from __future__ import annotations

import json

import pytest

from page_alchemist import publish as P
from page_alchemist.config import Settings
from page_alchemist.publish import NotionPublisher, StateStore, rich_text_payload
from page_alchemist.transform import TransformOptions, transform_document


class TestRichTextPayload:
    def test_long_run_split(self):
        from page_alchemist.models import RichText
        runs = rich_text_payload([RichText(text="x" * 5000)])
        assert len(runs) > 1
        assert all(len(r["text"]["content"]) <= P.RICH_TEXT_LIMIT for r in runs)

    def test_annotations_emitted_only_when_set(self):
        from page_alchemist.models import RichText
        plain = rich_text_payload([RichText(text="a")])
        assert "annotations" not in plain[0]          # no noise when unset
        bold = rich_text_payload([RichText(text="a", bold=True)])
        assert bold[0]["annotations"] == {"bold": True}
        combo = rich_text_payload([RichText(text="a", bold=True, code=True)])
        assert combo[0]["annotations"] == {"bold": True, "code": True}

    def test_link_wrapped(self):
        from page_alchemist.models import RichText
        out = rich_text_payload([RichText(text="t", link="https://x")])
        assert out[0]["text"]["link"] == {"url": "https://x"}


class TestChunking:
    def test_respects_limits(self, publish_doc):
        pub = NotionPublisher(Settings(state_dir="."), dry_run=True)
        units = pub._units(publish_doc.pages[0].blocks)
        chunks = P._chunks(units)
        assert all(len(c) <= P.MAX_APPEND for c in chunks)
        assert sum(len(c) for c in chunks) == len(units)

    def test_every_payload_is_flat_and_shaped(self, publish_doc):
        pub = NotionPublisher(Settings(state_dir="."), dry_run=True)
        units = pub._units(publish_doc.pages[0].blocks)
        for _pos, payload, _kids in units:
            assert isinstance(payload, dict) and "type" in payload
            # flat: no inline children anywhere (tables carry rows as units)
            blob = json.dumps(payload)
            assert '"children"' not in blob or payload["type"] == "table"

    def test_long_paragraph_becomes_multiple_units(self, publish_doc):
        pub = NotionPublisher(Settings(state_dir="."), dry_run=True)
        units = pub._units(publish_doc.pages[0].blocks)
        paras = [p for _pos, p, _k in units if p.get("type") == "paragraph"
                 and len(p["paragraph"]["rich_text"]) > 1]
        assert paras, "long paragraph was not split"

    def test_table_row_padded_to_width(self, publish_doc):
        pub = NotionPublisher(Settings(state_dir="."), dry_run=True)
        table = [b for b in publish_doc.pages[0].blocks if b.type == "table"][0]
        rows = pub._units([k for _p, k in pub._flat_units(table)][0])
        row_payloads = [p for _pos, p, _k in rows if p.get("type") == "table_row"]
        assert len(row_payloads) == 2
        assert len(row_payloads[1]["table_row"]["cells"]) == 2


class TestDryRunPublish:
    def test_full_plan(self, publish_doc, settings):
        pub = NotionPublisher(settings, dry_run=True)
        report = pub.publish(publish_doc,
                             "0123456789abcdef0123456789abcdef")
        assert report.errors == []
        assert report.pages_created == 2
        assert report.databases_created == 1
        assert report.rows_inserted == 2
        assert any("table_of_contents" in s for s in report.skipped)
        assert report.blocks_appended > 0

    def test_state_file_written(self, publish_doc, settings):
        from pathlib import Path
        pub = NotionPublisher(settings, dry_run=True)
        pub.publish(publish_doc, "0123456789abcdef0123456789abcdef")
        state_file = Path(settings.state_dir) / ".na_state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert len(data["pages"]) == 2
        assert data["target_parent"] == "0123456789abcdef0123456789abcdef"

    def test_resume_second_run(self, publish_doc, settings):
        pub = NotionPublisher(settings, dry_run=True)
        pub.publish(publish_doc, "0123456789abcdef0123456789abcdef")
        pub2 = NotionPublisher(settings, dry_run=True)
        report2 = pub2.publish(publish_doc,
                               "0123456789abcdef0123456789abcdef")
        assert report2.pages_created == 0
        assert report2.pages_reused == 2

    def test_icon_policy_applies_node_icon_only(self, publish_doc, settings):
        from page_alchemist.transform import RETUNE_EMOJI
        transform_document(publish_doc, TransformOptions(icon_mode="retune"))
        pub = NotionPublisher(settings, dry_run=True)
        root = publish_doc.pages[0]
        assert pub._icon_payload(root) == {"type": "emoji",
                                           "emoji": root.icon}
        assert root.icon in RETUNE_EMOJI


class TestStateStore:
    def test_round_trip_and_corrupt_tolerance(self, tmp_path):
        state_file = tmp_path / ".na_state.json"
        store = StateStore(state_file)
        store.set_page("abc", page_id="p1", units=3)
        again = StateStore(state_file)
        assert again.page_entry("abc")["units"] == 3
        state_file.write_text("{broken json", encoding="utf-8")
        tolerant = StateStore(state_file)          # must not raise
        assert tolerant.data["pages"] == {}

    def test_atomic_save_leaves_no_tmp(self, tmp_path):
        state_file = tmp_path / ".na_state.json"
        StateStore(state_file).save()
        assert not list(tmp_path.glob("*.tmp"))


class TestPublishEntry:
    def test_config_problems_raise(self, publish_doc, settings):
        from page_alchemist.publish import publish_document
        # parent given but no token -> the token problem must surface
        # (mirrors the CLI feeding --parent back into settings)
        settings.notion_token = ""
        settings.parent_page = "0123456789abcdef0123456789abcdef"
        with pytest.raises(ValueError, match="NOTION_TOKEN"):
            publish_document(publish_doc, settings,
                             parent_page_id="0123456789abcdef0123456789abcdef")

    def test_missing_parent_raises(self, publish_doc, settings):
        from page_alchemist.publish import publish_document
        settings.notion_token = "secret-token-abc"
        with pytest.raises(ValueError, match="NA_PARENT_PAGE"):
            publish_document(publish_doc, settings,
                             parent_page_id="")

    def test_dry_run_does_not_need_token(self, publish_doc):
        from page_alchemist.publish import publish_document
        settings = Settings(parent_page="0123456789abcdef0123456789abcdef",
                            state_dir=".")
        report = publish_document(publish_doc, settings, dry_run=True)
        assert report.errors == []
