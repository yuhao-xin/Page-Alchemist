"""Demo mode — run the whole pipeline offline against a synthetic source.

No credentials, no network: we build a fake "paid template library" document
that contains every artefact the Transform stage is meant to remove (branded
titles, colours, table-of-contents, breadcrumbs, synced blocks, duplicate
blocks, body H1s), then run Extract(IR) -> Transform -> Publish(--dry-run)
-> Markdown export and write everything into ``examples/demo_output/``.

This is what ``page-alchemist demo`` executes, and what the docs point at
when they say "try it before you configure anything".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .config import Settings
from .export_md import export_markdown
from .models import Block, Document, PageNode, RichText
from .transform import TransformOptions, transform_document
from .util import get_logger, now_iso

DEMO_SOURCE_URL = ("https://www.notion.so/@acme/Second-Brain-OS-"
                   "0123456789abcdef0123456789abcdef")


def _demo_png(path: Path) -> None:
    """A 1x1 transparent PNG — stands in for a downloaded asset."""
    if path.exists():
        return
    import zlib
    import struct

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    raw = b"\x00\x00\x00\x00\x00"
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sig + ihdr + idat + iend)


def build_demo_document(asset_dir: Path) -> Document:
    """A synthetic 'paid template library' full of markers to cleanse."""
    _demo_png(asset_dir / "diagram.png")

    dashboard = PageNode(
        source_id="11111111-1111-1111-1111-111111111111",
        title="🚀 【付费】Second Brain OS ★",
        icon="🎁",
        blocks=[
            Block(type="heading_1", text=[RichText(text="Welcome aboard",
                                                   color="red")]),
            Block(type="table_of_contents"),
            Block(type="breadcrumb"),
            Block(type="paragraph", text=[RichText(
                text="This operating system will 10x your productivity. " * 3,
                color="gray_background")]),
            Block(type="paragraph", text=[RichText(text="Buy the full course")]),
            Block(type="paragraph", text=[RichText(text="Buy the full course")]),
            Block(type="synced_block", children=[
                Block(type="callout", text=[RichText(text="Synced module: "
                                                       "weekly review")],
                      children=[Block(type="to_do",
                                      text=[RichText(text="Review inbox")],
                                      checked=False)]),
            ]),
            Block(type="heading_2", text=[RichText(text="Weekly review")]),
            Block(type="bulleted_list_item", text=[RichText(text="Collect")],
                  children=[Block(type="paragraph",
                                  text=[RichText(text="empty the inbox")])]),
            Block(type="numbered_list_item", text=[RichText(text="Clarify")]),
            Block(type="code", text=[RichText(text="make review")],
                  language="bash"),
            Block(type="table", raw={"table": {"table_width": 3}}, children=[
                Block(type="table_row", cells=[[RichText(text="Area")],
                                               [RichText(text="Cadence")],
                                               [RichText(text="Owner")]]),
                Block(type="table_row", cells=[[RichText(text="Inbox")],
                                               [RichText(text="daily")],
                                               [RichText(text="me")]]),
            ]),
            Block(type="image", url="https://example.com/remote-cover.png",
                  asset={"name": "remote-cover.png", "kind": "image",
                         "url": "https://example.com/remote-cover.png"}),
            Block(type="image", url="diagram.png",
                  asset={"name": "diagram.png", "kind": "image",
                         "url": "diagram.png",
                         "local_path": str(asset_dir / "diagram.png")}),
            Block(type="bookmark", url="https://example.com/course"),
            Block(type="link_to_page", text=[RichText(
                text="22222222-2222-2222-2222-222222222222", kind="mention")]),
        ],
        database={"schema": {"Task": "title", "Area": "select", "Done": "checkbox"},
                  "raw_schema": {"Task": {"type": "title"},
                                 "Area": {"type": "select",
                                          "select": {"options": [
                                              {"name": "Inbox"},
                                              {"name": "Projects"}]}},
                                 "Done": {"type": "checkbox"}},
                  "rows": [{"Task": "Clear inbox", "Area": "Inbox", "Done": True},
                           {"Task": "Plan week", "Area": "Projects", "Done": False}],
                  "row_count": 2},
        children=[],
    )

    review = PageNode(
        source_id="22222222-2222-2222-2222-222222222222",
        title="Weekly Review Playbook",
        icon="https://notion.so/signed-icon-url",
        blocks=[
            Block(type="heading_1", text=[RichText(text="The ritual")]),
            Block(type="paragraph", text=[RichText(text="Every Friday, 30 minutes.")]),
            Block(type="to_do", text=[RichText(text="Collect loose ends")], checked=True),
            Block(type="to_do", text=[RichText(text="Review projects")], checked=False),
        ],
        children=[PageNode(
            source_id="33333333-3333-3333-3333-333333333333",
            title="🎁 Bonus: Advanced Prompts",
            icon="⭐",
            blocks=[
                Block(type="paragraph", text=[RichText(
                    text="Prompt pack for the weekly review.", italic=True)]),
                Block(type="ai_block"),
                Block(type="quote", text=[RichText(text="Ship something weekly.")]),
            ],
        )],
    )
    dashboard.children.append(review)

    return Document(source_url=DEMO_SOURCE_URL, engine="api",
                    extracted_at=now_iso(), pages=[dashboard],
                    stats={"pages": 3, "blocks": 26})


def run_demo(out_dir: Path) -> Dict[str, Any]:
    """Execute the offline demo; returns a summary dict."""
    log = get_logger()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"

    # 1. Extract (synthetic) ------------------------------------------------ #
    doc = build_demo_document(assets)
    structure = out / "structure.json"
    structure.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    log.info("demo: extracted %d pages / %d blocks", len(doc.pages),
             doc.count_blocks())

    # 2. Transform ---------------------------------------------------------- #
    t_report = transform_document(doc, TransformOptions(icon_mode="retune"))
    transformed = out / "transformed.json"
    transformed.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2),
                           encoding="utf-8")
    (out / "transform-report.json").write_text(
        json.dumps(t_report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 3. Publish plan (dry run — no credentials needed) --------------------- #
    from .publish import NotionPublisher

    settings = Settings(parent_page="0123456789abcdef0123456789abcdef",
                        icon_mode="retune", state_dir=str(out))
    publisher = NotionPublisher(settings, dry_run=True)
    p_report = publisher.publish(doc, "0123456789abcdef0123456789abcdef")
    (out / "publish-report.json").write_text(
        json.dumps(p_report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 4. Markdown bundle ---------------------------------------------------- #
    md_report = export_markdown(doc, out / "bundle")
    (out / "markdown-report.json").write_text(
        json.dumps(md_report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8")

    summary = {
        "output_dir": str(out),
        "pages": sum(1 for _ in doc.iter_pages()),
        "blocks": doc.count_blocks(),
        "transform": t_report.summary(),
        "publish_plan": p_report.summary(),
        "markdown": md_report.summary(),
        "files": sorted(str(p.relative_to(out).as_posix())
                        for p in out.rglob("*") if p.is_file()),
    }
    (out / "demo-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
