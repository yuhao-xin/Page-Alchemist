"""Experimental export engine: Markdown parser and ZIP → IR."""
from __future__ import annotations

import zipfile

import pytest

from page_alchemist.models import Document
from page_alchemist.notion_unofficial import (parse_export_zip,
                                                parse_markdown)

MD_ROOT = """# Getting Started

Welcome to **the** starter kit. See [the docs](https://example.com/docs).

## Install

1. Clone the repo
2. Run `make install`

- [x] Create an integration
- [ ] Share the page
- plain bullet
- another *italic* bullet

> 💡 Tip: start with the demo page.

```python
print("hello")
```

---

| Feature | Status |
| --- | --- |
| Extract | done |
| Publish | wip |

![diagram](diagram.png)

[[NOTION-NOTE]] synced blocks and callouts survive as content.
"""

MD_CHILD = """# Advanced Usage

Nested bullets:

- one
  - one.a
  - one.b
- two

> quoted wisdom
"""


def build_zip(root):
    inner = root / "Getting Started 1a2b3c4d5e6f7a8b"
    inner.mkdir(parents=True)
    (inner / "Getting Started 1a2b3c4d5e6f7a8b.md").write_text(
        MD_ROOT, encoding="utf-8")
    (inner / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    child = inner / "Advanced Usage 9f8e7d6c5b4a3928"
    child.mkdir()
    (child / "Advanced Usage 9f8e7d6c5b4a3928.md").write_text(
        MD_CHILD, encoding="utf-8")
    (inner / "Tasks 0a1b2c3d4e5f6071.csv").write_text(
        "Name,Owner,Priority\nTask A,ann,high\nTask B,bob,low\n",
        encoding="utf-8")
    zip_path = root / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.name != "export.zip":
                zf.write(p, p.relative_to(root))
    return zip_path


@pytest.fixture()
def parsed_doc(tmp_path):
    zip_path = build_zip(tmp_path)
    return parse_export_zip(zip_path, extract_dir=tmp_path / "unzipped")


class TestParseMarkdown:
    def test_inline_formatting(self):
        blocks = parse_markdown(MD_ROOT)
        para = [b for b in blocks if b.type == "paragraph"][0]
        assert any(rt.bold for rt in para.text)
        assert any(rt.link for rt in para.text)

    def test_all_block_types(self):
        blocks = parse_markdown(MD_ROOT)
        types_seq = [b.type for b in blocks]
        for expected in ("heading_2", "code", "divider", "table", "image",
                         "callout", "to_do", "numbered_list_item",
                         "bulleted_list_item"):
            assert expected in types_seq, expected

    def test_nested_bullets(self):
        blocks = parse_markdown(MD_CHILD)
        bullets = [b for b in blocks if b.type == "bulleted_list_item"]
        assert len(bullets) == 2
        assert len(bullets[0].children) == 2
        assert bullets[0].children[0].plain_text() == "one.a"

    def test_code_language_captured(self):
        blocks = parse_markdown(MD_ROOT)
        code = [b for b in blocks if b.type == "code"][0]
        assert code.language == "python"
        assert "print(" in code.plain_text()

    def test_todo_checked_state(self):
        blocks = parse_markdown(MD_ROOT)
        todos = [b for b in blocks if b.type == "to_do"]
        assert todos[0].checked is True
        assert todos[1].checked is False

    def test_table_rows_and_width(self):
        blocks = parse_markdown(MD_ROOT)
        table = [b for b in blocks if b.type == "table"][0]
        assert table.raw["table"]["table_width"] == 2
        rows = [c for c in table.children if c.type == "table_row"]
        assert len(rows) == 3                       # header counts as a row
        assert rows[0].cells[0][0].text == "Feature"


class TestParseExportZip:
    def test_tree_shape(self, parsed_doc):
        doc, _extracted = parsed_doc
        assert isinstance(doc, Document)
        assert doc.engine == "export"
        assert len(doc.pages) == 1
        root = doc.pages[0]
        assert root.title == "Getting Started"
        assert len(root.children) == 1
        child = root.children[0]
        assert child.title == "Advanced Usage"
        assert child.path == ["Getting Started"]

    def test_title_h1_dropped(self, parsed_doc):
        doc, _ = parsed_doc
        types_seq = [b.type for b in doc.pages[0].blocks]
        assert "heading_1" not in types_seq
        assert types_seq[0] == "paragraph"

    def test_csv_becomes_database(self, parsed_doc):
        doc, _ = parsed_doc
        db = doc.pages[0].database
        assert db and db["row_count"] == 2
        assert db["rows"][0]["Name"] == "Task A"

    def test_image_asset_resolved(self, parsed_doc):
        from pathlib import Path
        doc, _ = parsed_doc
        image = [b for b in doc.pages[0].blocks if b.type == "image"][0]
        assert image.asset and image.asset.get("local_path")
        assert Path(image.asset["local_path"]).exists()

    def test_document_json_round_trip(self, parsed_doc):
        doc, _ = parsed_doc
        reloaded = Document.from_dict(doc.to_dict())
        assert reloaded.count_blocks() == doc.count_blocks()
