"""IR models: construction, JSON round-trip, counting."""
from __future__ import annotations

import json

from notion_alchemist.models import Block, Document, PageNode, RichText


def _small_doc() -> Document:
    return Document(
        source_url="https://www.notion.so/x-0123456789abcdef0123456789abcdef",
        engine="api",
        extracted_at="2026-10-18T00:00:00+00:00",
        pages=[PageNode(
            source_id="11111111-2222-3333-4444-555555555555",
            title="Root",
            blocks=[
                Block(type="heading_1", text=[RichText(text="H", bold=True)]),
                Block(type="table", raw={"table": {"table_width": 2}}, children=[
                    Block(type="table_row", cells=[[RichText(text="a")],
                                                   [RichText(text="b")]]),
                ]),
                Block(type="callout", children=[
                    Block(type="paragraph", text=[RichText(text="deep")])]),
            ],
            children=[PageNode(
                source_id="22222222-3333-4444-5555-666666666666",
                title="Child",
                blocks=[Block(type="paragraph", text=[RichText(text="c")])],
            )],
        )],
    )


class TestRichText:
    def test_round_trip(self):
        rt = RichText(text="hi", bold=True, italic=True, color="red",
                      link="https://x", kind="text")
        back = RichText.from_dict(rt.to_dict())
        assert back == rt

    def test_unknown_keys_ignored(self):
        back = RichText.from_dict({"text": "x", "bogus": 1})
        assert back.text == "x"


class TestBlock:
    def test_cells_round_trip(self):
        blk = Block(type="table_row",
                    cells=[[RichText(text="a", bold=True)]])
        back = Block.from_dict(blk.to_dict())
        assert back.cells[0][0].text == "a"
        assert back.cells[0][0].bold is True

    def test_nested_children_round_trip(self):
        blk = Block(type="toggle", children=[Block(type="paragraph",
                                                   text=[RichText(text="t")])])
        back = Block.from_dict(blk.to_dict())
        assert back.children[0].plain_text() == "t"

    def test_plain_text(self):
        blk = Block(text=[RichText(text="a"), RichText(text="b")])
        assert blk.plain_text() == "ab"


class TestPageNode:
    def test_ensure_slug_is_idempotent(self):
        node = PageNode(title="My Page")
        assert node.ensure_slug() == "my-page"
        assert node.ensure_slug() == "my-page"


class TestDocument:
    def test_iter_pages_depth_first(self):
        doc = _small_doc()
        titles = [p.title for p, _d in doc.iter_pages()]
        assert titles == ["Root", "Child"]

    def test_count_blocks_page_level_only(self):
        # page-level blocks are counted; block-level nesting (table_row,
        # callout children) is not — and child pages are never double counted
        doc = _small_doc()
        # root: heading + table + callout = 3; child page: paragraph = 1
        assert doc.count_blocks() == 4

    def test_json_round_trip_preserves_tree(self):
        doc = _small_doc()
        reloaded = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
        assert reloaded.count_blocks() == doc.count_blocks()
        assert [p.title for p, _ in reloaded.iter_pages()] == ["Root", "Child"]
        table = [b for b in reloaded.pages[0].blocks if b.type == "table"][0]
        assert table.children[0].cells[0][0].text == "a"
        assert table.raw["table"]["table_width"] == 2
