"""Markdown export: rendering fidelity and bundle layout."""
from __future__ import annotations

from page_alchemist.export_md import export_markdown, render_page_md, render_rich_text
from page_alchemist.models import Block, Document, PageNode, RichText


def _page() -> PageNode:
    return PageNode(
        source_id="11111111-2222-3333-4444-555555555555",
        title="Guide",
        blocks=[
            Block(type="heading_2", text=[RichText(text="Install")]),
            Block(type="paragraph", text=[RichText(text="do **this** first")]),
            Block(type="bulleted_list_item", text=[RichText(text="one")],
                  children=[Block(type="paragraph",
                                  text=[RichText(text="nested note")])]),
            Block(type="numbered_list_item", text=[RichText(text="step")]),
            Block(type="to_do", text=[RichText(text="done")], checked=True),
            Block(type="to_do", text=[RichText(text="todo")], checked=False),
            Block(type="callout", text=[RichText(text="💡 hint")]),
            Block(type="code", text=[RichText(text="print(1)")],
                  language="python"),
            Block(type="divider"),
            Block(type="table", raw={"table": {"table_width": 2}}, children=[
                Block(type="table_row",
                      cells=[[RichText(text="A")], [RichText(text="B")]]),
                Block(type="table_row",
                      cells=[[RichText(text="1")], [RichText(text="2")]]),
            ]),
            Block(type="image", url="https://example.com/x.png"),
            Block(type="bookmark", url="https://example.com"),
        ],
        children=[PageNode(source_id="22222222-3333-4444-5555-666666666666",
                           title="Child",
                           blocks=[Block(type="paragraph",
                                         text=[RichText(text="c")])])],
    )


class TestRenderRichText:
    def test_escapes_markdown_specials(self):
        # escape set is \ ` * [ ] |  (underscore deliberately not escaped)
        out = render_rich_text([RichText(text="a*b_c[d]e`f|g")])
        assert out == r"a\*b_c\[d\]e\`f\|g"

    def test_bold_italic_code(self):
        assert render_rich_text([RichText(text="x", bold=True)]) == "**x**"
        assert render_rich_text([RichText(text="x", italic=True)]) == "*x*"
        assert render_rich_text([RichText(text="x", code=True)]) == "`x`"

    def test_link(self):
        out = render_rich_text([RichText(text="t", link="https://x")])
        assert out == "[t](https://x)"


class TestRenderPage:
    def test_all_block_types_render(self):
        md = render_page_md(_page())
        assert "# Guide" in md
        assert "## Install" in md
        assert "- one" in md
        assert "  nested note" in md          # nested paragraph indented
        assert "1. step" in md
        assert "- [x] done" in md
        assert "- [ ] todo" in md
        assert "```python" in md and "print(1)" in md
        assert "| A | B |" in md
        assert "![image](https://example.com/x.png)" in md
        assert "https://example.com" in md    # bookmark

    def test_table_has_separator_row(self):
        md = render_page_md(_page())
        assert "| --- | --- |" in md


class TestExportMarkdown:
    def test_bundle_layout(self, tmp_path):
        doc = Document(source_url="u", engine="api", pages=[_page()])
        out = tmp_path / "bundle"
        report = export_markdown(doc, out)
        assert report.pages == 2
        assert (out / "guide" / "guide.md").exists()
        assert (out / "guide" / "child" / "child.md").exists()
        assert (out / "INDEX.md").exists()

    def test_local_asset_preferred_over_url(self, tmp_path):
        asset = tmp_path / "diagram.png"
        asset.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        page = PageNode(title="P", blocks=[
            Block(type="image", url="https://example.com/x.png",
                  asset={"name": "diagram.png", "local_path": str(asset)})])
        doc = Document(engine="api", pages=[page])
        out = tmp_path / "bundle"
        export_markdown(doc, out)
        md = (out / "p" / "p.md").read_text(encoding="utf-8")
        assert "![diagram.png](assets/diagram.png)" in md
        assert (out / "p" / "assets" / "diagram.png").exists()

    def test_missing_asset_reported(self, tmp_path):
        page = PageNode(title="P", blocks=[
            Block(type="image", asset={"name": "gone.png",
                                       "local_path": str(tmp_path / "gone.png")})])
        doc = Document(engine="api", pages=[page])
        report = export_markdown(doc, tmp_path / "bundle")
        assert any("gone.png" in s for s in report.skipped)
