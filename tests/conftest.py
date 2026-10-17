"""Shared pytest setup.

Two jobs:

1. put ``src/`` on ``sys.path`` so the suite runs from a checkout without
   installing the package;
2. stub ``requests`` when it is not installed, so network-touching modules
   import (and dry-run paths execute) in a dependency-free environment.
   When ``requests`` *is* installed the real module is used untouched.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _install_requests_stub() -> None:
    if "requests" in sys.modules:
        return
    try:
        import requests  # noqa: F401
        return
    except ImportError:
        pass
    stub = types.ModuleType("requests")

    class _Session:
        def __init__(self):
            self.headers = {}

        def request(self, *a, **kw):
            raise AssertionError("unexpected HTTP call in tests")

        def get(self, *a, **kw):
            raise AssertionError("unexpected HTTP call in tests")

        def post(self, *a, **kw):
            raise AssertionError("unexpected HTTP call in tests")

    stub.Session = _Session
    stub.get = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("unexpected HTTP call in tests"))
    sys.modules["requests"] = stub


_install_requests_stub()

import pytest  # noqa: E402

from notion_alchemist.models import Block, Document, PageNode, RichText  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def transform_doc() -> Document:
    """A source template carrying every mess transform is meant to clean."""
    return Document(
        source_url="https://www.notion.so/@acme/Paid-Template-Library-"
                   "0123456789abcdef0123456789abcdef",
        engine="api",
        extracted_at="2026-10-18T09:00:00+08:00",
        pages=[PageNode(
            source_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            title="📚 【付费】 Ultimate Notion Template ★",
            icon="🎁",
            blocks=[
                Block(type="heading_1", text=[RichText(text="Body H1")]),
                Block(type="table_of_contents"),
                Block(type="breadcrumb"),
                Block(type="paragraph",
                      text=[RichText(text="Coloured text", color="red_background")]),
                Block(type="paragraph", text=[RichText(text="same")]),
                Block(type="paragraph", text=[RichText(text="same")]),
                Block(type="synced_block", children=[
                    Block(type="paragraph", text=[RichText(text="synced body")]),
                    Block(type="ai_block"),
                ]),
                Block(type="heading_2", text=[RichText(text="Section A")]),
                Block(type="divider"),
                Block(type="child_database", text=[RichText(text="Tasks")]),
                Block(type="paragraph", text=[RichText(text="", color="blue")]),
            ],
            children=[PageNode(
                source_id="ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb",
                title="Child Page",
                icon="https://notion.so/signed-icon-url",
                blocks=[Block(type="heading_1", text=[RichText(text="only h1")])],
            )],
        )],
    )


@pytest.fixture()
def publish_doc() -> Document:
    """A document exercising every publish-path payload shape."""
    return Document(
        source_url="https://www.notion.so/example/Source-Page-"
                   "0123456789abcdef0123456789abcdef",
        engine="api",
        extracted_at="2026-10-18T00:00:00+00:00",
        pages=[PageNode(
            source_id="11111111-2222-3333-4444-555555555555",
            title="Source Page",
            icon="🧪",
            blocks=[
                Block(type="heading_1", text=[RichText(text="Intro", bold=True)]),
                Block(type="paragraph",
                      text=[RichText(text="A long paragraph. " * 300)]),  # >2000
                Block(type="bulleted_list_item", text=[RichText(text="one")],
                      children=[Block(type="paragraph",
                                      text=[RichText(text="nested one")])]),
                Block(type="to_do", text=[RichText(text="task")], checked=True),
                Block(type="code", text=[RichText(text="print(1)")],
                      language="python"),
                Block(type="callout", text=[RichText(text="note")],
                      children=[Block(type="paragraph",
                                      text=[RichText(text="inside")])]),
                Block(type="divider"),
                Block(type="table_of_contents"),                     # dropped
                Block(type="synced_block", children=[                # unwrapped
                    Block(type="paragraph", text=[RichText(text="synced content")]),
                ]),
                Block(type="table", raw={"table": {"table_width": 2}}, children=[
                    Block(type="table_row",
                          cells=[[RichText(text="a")], [RichText(text="b")]]),
                    Block(type="table_row", cells=[[RichText(text="c")]]),
                ]),
                Block(type="column_list", children=[
                    Block(type="column", children=[Block(
                        type="paragraph", text=[RichText(text="col")])]),
                ]),
                Block(type="image", url="https://example.com/x.png"),
                Block(type="bookmark", url="https://example.com"),
                Block(type="link_to_page",
                      text=[RichText(text="11111111-2222-3333-4444-555555555555",
                                     kind="mention")]),
                Block(type="child_page", text=[RichText(text="Orphan Page")]),
            ],
            children=[PageNode(
                source_id="66666666-7777-8888-9999-000000000000",
                title="Child Page",
                blocks=[Block(type="paragraph", text=[RichText(text="child body")])],
            )],
            database={
                "schema": {"Name": "title", "Tags": "multi_select"},
                "raw_schema": {"Name": {"type": "title"},
                               "Tags": {"type": "multi_select",
                                        "multi_select": {"options": [
                                            {"name": "x"}, {"name": "y"}]}}},
                "rows": [{"Name": "row1", "Tags": ["x", "y"]},
                         {"Name": "row2", "Tags": ["x"]}],
                "row_count": 2,
            },
        )],
    )


@pytest.fixture()
def settings(tmp_path):
    from notion_alchemist.config import Settings
    return Settings(notion_token="secret-token-abc", parent_page="",
                    icon_mode="retune", state_dir=str(tmp_path / "state"))
