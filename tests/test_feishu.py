"""Tests for the Feishu/Lark publish engine.

The HTTP surface is faked at the session level (the same seam
``FeishuClient`` offers), so no network and no ``requests`` install are
needed — the conftest stub raises on any *unexpected* HTTP call, which is
exactly the dry-run assertion we want.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from page_alchemist import feishu as F
from page_alchemist.config import Settings
from page_alchemist.feishu import (
    FeishuApiError,
    FeishuClient,
    FeishuPublisher,
    chunk_plan,
    convert_blocks,
    database_blocks,
    publish_to_feishu,
)
from page_alchemist.models import Block, Document, PageNode, RichText


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeFeishuSession:
    """Records every call; replies with plausible Feishu envelopes."""

    def __init__(self):
        self.headers = {}
        self.calls = []           # (method, url, json body)
        self.posts = []           # (url, data dict)
        self._doc_n = 0

    def _reply(self, payload):
        return SimpleNamespace(status_code=200, content=b"{}",
                               headers={}, text="",
                               json=lambda: payload)

    def request(self, method, url, *, params=None, json=None, headers=None,
                timeout=None, **kw):
        self.calls.append((method, url, json))
        if url.endswith("/tenant_access_token/internal"):
            return self._reply({"code": 0, "tenant_access_token": "t-abc",
                                "expire": 7200})
        if url.endswith("/docx/v1/documents"):
            self._doc_n += 1
            return self._reply({"code": 0, "data": {
                "document": {"document_id": f"doc{self._doc_n}"}}})
        if "/descendant" in url:
            return self._reply({"code": 0, "data": {"children": []}})
        return self._reply({"code": 0, "data": {}})

    def post(self, url, *, files=None, data=None, headers=None,
             timeout=None, **kw):
        self.posts.append((url, data))
        return self._reply({"code": 0, "data": {"file_token": "tok-123"}})


def make_settings(tmp_path, **over):
    s = Settings(notion_token="secret-token-abc", parent_page="",
                 icon_mode="retune", state_dir=str(tmp_path / "state"))
    s.feishu_app_id = "cli_app123"
    s.feishu_app_secret = "sec456"
    for k, v in over.items():
        setattr(s, k, v)
    return s


def feishu_doc():
    """A small two-page document with a representative block mix."""
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
                Block(type="heading_1", text=[RichText(text="Intro")]),
                Block(type="paragraph",
                      text=[RichText(text="A ", bold=True),
                            RichText(text="link", link="https://x.dev")]),
                Block(type="bulleted_list_item", text=[RichText(text="one")],
                      children=[Block(type="paragraph",
                                      text=[RichText(text="nested")])]),
                Block(type="to_do", text=[RichText(text="task")], checked=True),
                Block(type="code", text=[RichText(text="print(1)")],
                      language="python"),
                Block(type="callout", text=[RichText(text="note")]),
                Block(type="divider"),
                Block(type="bookmark", url="https://example.com"),
                Block(type="table", children=[
                    Block(type="table_row",
                          cells=[[RichText(text="a")], [RichText(text="b")]]),
                    Block(type="table_row", cells=[[RichText(text="c")]]),
                ]),
            ],
            children=[PageNode(
                source_id="66666666-7777-8888-9999-000000000000",
                title="Child Page",
                blocks=[Block(type="paragraph",
                              text=[RichText(text="child body")])],
            )],
            database={"schema": {"Name": "title", "Tags": "multi_select"},
                      "rows": [{"Name": "row1", "Tags": ["x", "y"]}],
                      "row_count": 1},
        )],
    )


# --------------------------------------------------------------------------- #
# token / client
# --------------------------------------------------------------------------- #
class TestFeishuClient:
    def test_token_cached_across_requests(self, tmp_path):
        session = FakeFeishuSession()
        client = FeishuClient(make_settings(tmp_path), session=session)
        client.create_document("t")
        client.create_document("t2")
        auth_calls = [c for c in session.calls
                      if c[1].endswith("/tenant_access_token/internal")]
        assert len(auth_calls) == 1

    def test_app_error_code_raises(self, tmp_path):
        session = FakeFeishuSession()

        def broken(method, url, **kw):
            session.calls.append((method, url, kw.get("json")))
            return SimpleNamespace(status_code=200, content=b"{}",
                                   headers={}, text="",
                                   json=lambda: {"code": 99991672,
                                                 "msg": "permission denied"})

        session.request = broken
        client = FeishuClient(make_settings(tmp_path), session=session)
        with pytest.raises(FeishuApiError, match="99991672"):
            client.create_document("t")

    def test_lark_base_switches_host(self, tmp_path):
        client = FeishuClient(make_settings(tmp_path, feishu_base=F.LARK_BASE))
        assert client.base == F.LARK_BASE
        assert F.document_url("d1", F.LARK_BASE) == \
            "https://www.larksuite.com/docx/d1"


# --------------------------------------------------------------------------- #
# block conversion
# --------------------------------------------------------------------------- #
class TestConversion:
    def test_core_block_shapes(self):
        children_id, descendants = convert_blocks([
            Block(type="heading_1", text=[RichText(text="H")]),
            Block(type="paragraph",
                  text=[RichText(text="A ", bold=True),
                        RichText(text="link", link="https://x.dev")]),
            Block(type="to_do", text=[RichText(text="t")], checked=True),
            Block(type="code", text=[RichText(text="x=1")], language="python"),
            Block(type="divider"),
            Block(type="bookmark", url="https://e.com"),
        ])
        assert len(children_id) == 6
        by_id = {d["block_id"]: d for d in descendants}
        h1 = by_id[children_id[0]]
        assert h1["block_type"] == F.T_H1
        assert h1["heading1"]["elements"][0]["text_run"]["content"] == "H"
        para = by_id[children_id[1]]
        assert para["block_type"] == F.T_TEXT
        assert para["text"]["elements"][0]["text_run"]["text_element_style"]["bold"] \
            is True
        assert para["text"]["elements"][1]["text_run"]["text_element_style"]["link"]["url"] \
            == "https://x.dev"
        todo = by_id[children_id[2]]
        assert todo["block_type"] == F.T_TODO
        assert todo["todo"]["done"] is True
        code = by_id[children_id[3]]
        assert code["code"]["language"] == 47          # Python in the enum
        assert by_id[children_id[4]]["divider"] == {}
        link = by_id[children_id[5]]
        assert link["text"]["elements"][0]["text_run"]["text_element_style"]["link"]["url"] \
            == "https://e.com"

    def test_inline_styles_map_to_element_style(self):
        _, descendants = convert_blocks([Block(
            type="paragraph",
            text=[RichText(text="styled", bold=True, italic=True,
                           strikethrough=True, underline=True, code=True)])])
        style = descendants[0]["text"]["elements"][0]["text_run"][
            "text_element_style"]
        assert style == {"bold": True, "italic": True, "strikethrough": True,
                         "underline": True, "inline_code": True}

    def test_nested_children_are_referenced(self):
        _, descendants = convert_blocks([Block(
            type="bulleted_list_item", text=[RichText(text="parent")],
            children=[Block(type="paragraph",
                            text=[RichText(text="kid")])])])
        by_id = {d["block_id"]: d for d in descendants}
        parent = descendants[0]
        assert parent["block_type"] == F.T_BULLET
        assert parent["children"] == [d["block_id"] for d in descendants[1:]]
        assert by_id[parent["children"][0]]["block_type"] == F.T_TEXT

    def test_synced_and_column_containers_are_unwrapped(self):
        _, descendants = convert_blocks([
            Block(type="synced_block", children=[
                Block(type="paragraph", text=[RichText(text="inner")])]),
            Block(type="column_list", children=[
                Block(type="column", children=[
                    Block(type="paragraph", text=[RichText(text="col")])])]),
        ])
        assert [d["block_type"] for d in descendants] == [F.T_TEXT, F.T_TEXT]
        assert len(descendants) == 2

    def test_noise_types_drop_silently(self):
        _, descendants = convert_blocks([
            Block(type="table_of_contents"),
            Block(type="breadcrumb"),
            Block(type="child_page", text=[RichText(text="Orphan")]),
            Block(type="child_database", text=[RichText(text="DB")]),
            Block(type="link_to_page",
                  text=[RichText(text="11111111-2222-3333-4444-555555555555",
                                 kind="mention")]),
        ])
        assert descendants == []

    def test_empty_paragraph_dropped(self):
        _, descendants = convert_blocks([Block(type="paragraph", text=[])])
        assert descendants == []

    def test_unknown_type_degrades_to_text(self):
        _, descendants = convert_blocks(
            [Block(type="ai_snippet", text=[RichText(text="kept")])])
        assert len(descendants) == 1
        assert descendants[0]["block_type"] == F.T_TEXT
        assert descendants[0]["text"]["elements"][0]["text_run"]["content"] \
            == "kept"

    def test_equation_becomes_inline_code(self):
        _, descendants = convert_blocks(
            [Block(type="equation", text=[RichText(text="E=mc^2")])])
        style = descendants[0]["text"]["elements"][0]["text_run"][
            "text_element_style"]
        assert style["inline_code"] is True

    def test_image_with_local_file_uploads(self, tmp_path):
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        seen = []

        def upload(path):
            seen.append(path)
            return "tok-123"

        _, descendants = convert_blocks(
            [Block(type="image", asset={"local_path": str(png),
                                        "url": "https://e/x.png"})],
            upload_image=upload)
        assert seen == [png]
        assert descendants[0]["image"]["token"] == "tok-123"

    def test_remote_image_degrades_to_link(self):
        _, descendants = convert_blocks(
            [Block(type="image", asset={"url": "https://e/x.png"})])
        assert descendants[0]["block_type"] == F.T_TEXT
        assert "https://e/x.png" in \
            descendants[0]["text"]["elements"][0]["text_run"]["content"]


class TestTables:
    def test_table_block_shape(self):
        _, descendants = convert_blocks([Block(type="table", children=[
            Block(type="table_row", cells=[[RichText(text="a")],
                                           [RichText(text="b")]]),
            Block(type="table_row", cells=[[RichText(text="c")],
                                           [RichText(text="d")]]),
        ])])
        table = descendants[0]
        assert table["block_type"] == F.T_TABLE
        assert table["table"]["property"] == {"row_size": 2, "column_size": 2}
        # table + 4 cells + 4 cell texts
        assert len(descendants) == 9
        cells = [d for d in descendants if d["block_type"] == F.T_TABLE_CELL]
        assert len(cells) == 4
        assert all(c["children"] for c in cells)

    def test_wide_table_degrades_to_lines(self):
        wide = Block(type="table", children=[
            Block(type="table_row",
                  cells=[[RichText(text=f"c{i}")] for i in range(25)]),
        ])
        _, descendants = convert_blocks([wide])
        assert all(d["block_type"] == F.T_TEXT for d in descendants)
        assert "c0 | c1" in descendants[0]["text"]["elements"][0][
            "text_run"]["content"]

    def test_database_rows_render_as_table(self):
        alloc = F._IdAllocator()
        blocks = database_blocks(
            {"schema": {"Name": "title", "Tags": "multi_select"},
             "rows": [{"Name": "row1", "Tags": ["x", "y"]}],
             "row_count": 1}, alloc)
        assert blocks[0]["block_type"] == F.T_TABLE
        assert blocks[0]["table"]["property"]["row_size"] == 2  # header + row
        assert blocks[0]["table"]["property"]["column_size"] == 2
        texts = [d for d in blocks if d["block_type"] == F.T_TEXT]
        joined = " ".join(t["text"]["elements"][0]["text_run"]["content"]
                          for t in texts)
        assert "Name" in joined and "row1" in joined and "x, y" in joined


# --------------------------------------------------------------------------- #
# batching
# --------------------------------------------------------------------------- #
class TestChunkPlan:
    def test_batches_respect_limit_with_subtrees(self):
        blocks = [Block(type="bulleted_list_item",
                        text=[RichText(text=f"i{i}")],
                        children=[Block(type="paragraph",
                                        text=[RichText(text="kid")])])
                  for i in range(120)]  # 120 * 2 = 240 blocks
        children_id, descendants = convert_blocks(blocks)
        assert len(descendants) == 240
        batches = chunk_plan(children_id, descendants, limit=100)
        assert len(batches) == 3
        assert all(len(b[1]) <= 100 for b in batches)
        # every top-level block appears exactly once, in order
        flat = [cid for b in batches for cid in b[0]]
        assert flat == children_id

    def test_oversized_subtree_goes_alone(self):
        big = Block(type="bulleted_list_item",
                    text=[RichText(text="root")],
                    children=[Block(type="paragraph",
                                    text=[RichText(text=f"k{i}")])
                              for i in range(150)])
        children_id, descendants = convert_blocks([big])
        batches = chunk_plan(children_id, descendants, limit=100)
        assert len(batches) == 1
        assert len(batches[0][1]) == 151


# --------------------------------------------------------------------------- #
# publisher end-to-end (faked HTTP)
# --------------------------------------------------------------------------- #
class TestPublisher:
    def test_full_publish_creates_one_document_per_page(self, tmp_path):
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        pub = FeishuPublisher(settings, session=session)
        report = pub.publish(feishu_doc())

        assert report.errors == []
        assert report.documents_created == 2
        assert report.documents_reused == 0
        doc_calls = [c for c in session.calls
                     if c[1].endswith("/docx/v1/documents")]
        assert len(doc_calls) == 2
        assert doc_calls[0][2]["title"] == "Source Page"
        desc_calls = [c for c in session.calls if "/descendant" in c[1]]
        assert len(desc_calls) >= 2
        # breadcrumb callout rides first in every document
        for _, _, body in desc_calls:
            assert body["descendants"][0]["block_type"] == F.T_CALLOUT
            assert body["children_id"][0] == "breadcrumb"
        assert report.documents[0]["url"].startswith("https://www.feishu.cn/")

    def test_state_makes_rerun_idempotent(self, tmp_path):
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        FeishuPublisher(settings, session=session).publish(feishu_doc())
        calls_after_first = len(session.calls)
        assert calls_after_first > 0  # the first run really did talk to Feishu

        session2 = FakeFeishuSession()
        report2 = FeishuPublisher(settings, session=session2).publish(
            feishu_doc())
        assert report2.documents_created == 0
        assert report2.documents_reused == 2
        assert len(session2.calls) == 0  # nothing to do, no HTTP at all

    def test_partial_document_is_refilled_not_duplicated(self, tmp_path):
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        pub = FeishuPublisher(settings, session=session)
        doc = feishu_doc()
        pub.publish(doc)
        # simulate a crash after document creation but before blocks landed
        state_file = Path(settings.state_dir) / F.STATE_FILENAME
        data = json.loads(state_file.read_text(encoding="utf-8"))
        for entry in data["pages"].values():
            entry["units"] = 0
        state_file.write_text(json.dumps(data), encoding="utf-8")

        session2 = FakeFeishuSession()
        report2 = FeishuPublisher(settings, session=session2).publish(doc)
        assert report2.documents_created == 0
        assert report2.documents_refilled == 2
        # re-fill reuses the SAME document ids (no new create calls)
        doc_calls = [c for c in session2.calls
                     if c[1].endswith("/docx/v1/documents")]
        assert doc_calls == []
        desc_calls = [c for c in session2.calls if "/descendant" in c[1]]
        assert len(desc_calls) >= 2
        assert all("doc1" in c[1] or "doc2" in c[1] for c in desc_calls)

    def test_folder_token_forwarded(self, tmp_path):
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        FeishuPublisher(settings, session=session).publish(
            feishu_doc(), folder_token="fld-abc")
        doc_calls = [c for c in session.calls
                     if c[1].endswith("/docx/v1/documents")]
        assert all(c[2]["folder_token"] == "fld-abc" for c in doc_calls)

    def test_page_failure_does_not_abort_run(self, tmp_path):
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        pub = FeishuPublisher(settings, session=session)
        # make the second create_document fail with a non-retryable error
        original = session.request
        state = {"n": 0}

        def flaky(method, url, **kw):
            if url.endswith("/docx/v1/documents"):
                state["n"] += 1
                if state["n"] == 2:
                    return SimpleNamespace(
                        status_code=400, content=b"{}", headers={},
                        text='{"code": 1069902, "msg": "folder not found"}',
                        json=lambda: {"code": 1069902,
                                      "msg": "folder not found"})
            return original(method, url, **kw)

        session.request = flaky
        report = pub.publish(feishu_doc())
        assert len(report.errors) == 1
        assert "folder not found" in report.errors[0]
        assert report.documents_created == 1  # the good page still landed

    def test_dry_run_makes_no_http_calls(self, tmp_path):
        # the conftest requests-stub raises on any session use; dry-run must
        # not even construct a client
        settings = make_settings(tmp_path)
        report = publish_to_feishu(feishu_doc(), settings, dry_run=True)
        assert report.documents_created == 0
        assert report.documents_total == 2
        assert len(report.documents) == 2
        assert all(d["url"].startswith("https://www.feishu.cn/docx/dry-run-")
                   for d in report.documents)

    def test_missing_credentials_raise(self, tmp_path):
        settings = make_settings(tmp_path, feishu_app_id="",
                                 feishu_app_secret="")
        with pytest.raises(ValueError, match="NA_FEISHU_APP_ID"):
            publish_to_feishu(feishu_doc(), settings)
        settings = make_settings(tmp_path, feishu_app_secret="")
        with pytest.raises(ValueError, match="NA_FEISHU_APP_SECRET"):
            publish_to_feishu(feishu_doc(), settings)

    def test_bad_base_raises(self, tmp_path):
        settings = make_settings(tmp_path, feishu_base="https://evil.example")
        with pytest.raises(ValueError, match="NA_FEISHU_BASE"):
            publish_to_feishu(feishu_doc(), settings)

    def test_image_upload_uses_media_endpoint(self, tmp_path):
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        session = FakeFeishuSession()
        settings = make_settings(tmp_path)
        doc = Document(pages=[PageNode(
            source_id="11111111-2222-3333-4444-555555555555",
            title="P",
            blocks=[Block(type="image",
                          asset={"local_path": str(png)})])])
        report = FeishuPublisher(settings, session=session).publish(doc)
        assert report.images_uploaded == 1
        assert session.posts and session.posts[0][0].endswith(
            "/open-apis/drive/v1/medias/upload_all")
        assert session.posts[0][1]["parent_type"] == "docx_image"
