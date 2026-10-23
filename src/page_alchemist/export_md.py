"""Markdown export — turn the (transformed) IR into an import-ready bundle.

The bundle mirrors Notion's own Markdown & CSV export layout, so it can be
zipped and re-imported into any Notion workspace (``Import → Markdown & CSV``)
without going through the API at all:

    <out>/<page-slug>/<page-slug>.md     one file per page
    <out>/<page-slug>/assets/<file>      local assets, referenced relatively
    <out>/<page-slug>/<db>.csv           databases as CSV
    <out>/INDEX.md                       navigation index
"""
from __future__ import annotations

import csv
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List

from .models import Block, Document, PageNode, RichText
from .util import get_logger, safe_filename

_ESCAPE_RE = re.compile(r"([\\`*\[\]|])")


@dataclass
class ExportReport:
    pages: int = 0
    files: int = 0
    assets: int = 0
    csv_files: int = 0
    output_dir: str = ""
    skipped: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return (f"{self.pages} pages, {self.files} markdown files, "
                f"{self.csv_files} csv, {self.assets} assets -> {self.output_dir}")


# --------------------------------------------------------------------------- #
# Inline rendering
# --------------------------------------------------------------------------- #
def _escape(text: str) -> str:
    return _ESCAPE_RE.sub(r"\\\1", text)


def render_rich_text(items: List[RichText]) -> str:
    out: List[str] = []
    for rt in items or []:
        if not rt.text:
            continue
        if rt.code:
            out.append(f"`{rt.text}`")
            continue
        text = _escape(rt.text)
        if rt.link:
            text = f"[{text}]({rt.link})"
        if rt.bold and rt.italic:
            text = f"***{text}***"
        elif rt.bold:
            text = f"**{text}**"
        elif rt.italic:
            text = f"*{text}*"
        if rt.strikethrough:
            text = f"~~{text}~~"
        out.append(text)
    return "".join(out)


# --------------------------------------------------------------------------- #
# Block rendering
# --------------------------------------------------------------------------- #
def _render_list_item(block: Block, indent: int, numbered: bool) -> List[str]:
    prefix = " " * (indent * 2) + ("1. " if numbered else "- ")
    if block.type == "to_do":
        prefix = " " * (indent * 2) + ("- [x] " if block.checked else "- [ ] ")
    lines = [prefix + render_rich_text(block.text)]
    for child in block.children:
        lines.extend(_render_block(child, indent + 1))
    return lines


def _render_block(block: Block, indent: int = 0) -> List[str]:
    t = block.type
    if t in ("heading_1", "heading_2", "heading_3"):
        return ["#" * int(t[-1]) + " " + render_rich_text(block.text)]
    if t == "paragraph":
        text = render_rich_text(block.text)
        return [(" " * (indent * 2) + text)] if text else []
    if t in ("bulleted_list_item", "numbered_list_item", "to_do"):
        return _render_list_item(block, indent, t == "numbered_list_item")
    if t == "code":
        lang = block.language or ""
        return [f"```{lang}", block.plain_text(), "```"]
    if t == "quote":
        text = render_rich_text(block.text)
        return [f"> {line}" for line in text.split("\n")] if text else []
    if t == "callout":
        text = render_rich_text(block.text)
        lines = [f"> 💡 {line}" if i == 0 else f"> {line}"
                 for i, line in enumerate(text.split("\n"))]
        for child in block.children:
            lines.extend("> " + sub for sub in _render_block(child))
        return lines
    if t == "divider":
        return ["---"]
    if t == "image":
        alt = (block.asset or {}).get("name") or "image"
        local = (block.asset or {}).get("local_path")
        # prefer the bundled asset; fall back to the (possibly signed) url
        src = f"assets/{Path(local).name}" if local else (block.url or "")
        return [f"![{alt}]({src})"]
    if t in ("bookmark", "embed", "link_preview"):
        return [f"[{block.url}]({block.url})"] if block.url else []
    if t in ("child_page", "child_database"):
        title = block.plain_text() or "Untitled"
        mark = "📄" if t == "child_page" else "🗃️"
        return [f"{mark} {title}"]
    if t == "link_to_page":
        return [f"🔗 {block.plain_text() or 'linked page'}"]
    if t == "table":
        return _render_table(block)
    if t == "column_list":
        lines: List[str] = []
        for column in block.children:
            for child in column.children:
                lines.extend(_render_block(child))
        return lines
    if t == "column":
        lines = []
        for child in block.children:
            lines.extend(_render_block(child))
        return lines
    if t == "table_row":
        return [" | ".join(render_rich_text(cell) for cell in block.cells)]
    # unknown: keep the text
    text = render_rich_text(block.text)
    return [text] if text else []


def _render_table(block: Block) -> List[str]:
    rows = [c for c in block.children if c.type == "table_row"]
    if not rows:
        return []
    width = (block.raw.get("table") or {}).get("table_width") or max(
        len(r.cells) for r in rows)
    header = rows[0]
    lines = ["| " + " | ".join(render_rich_text(cell)
                                for cell in (header.cells + [[]] * width)[:width]) + " |",
             "| " + " | ".join("---" for _ in range(width)) + " |"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(
            render_rich_text(cell) for cell in (row.cells + [[]] * width)[:width]) + " |")
    return lines


def render_page_md(node: PageNode) -> str:
    lines: List[str] = [f"# {node.title}", ""]
    for block in node.blocks:
        rendered = _render_block(block)
        if rendered:
            lines.extend(rendered)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Bundle export
# --------------------------------------------------------------------------- #
def export_markdown(doc: Document, out_dir: Path, *,
                    copy_assets: bool = True) -> ExportReport:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport(output_dir=str(out))
    log = get_logger()
    index: List[str] = ["# Archive index", ""]

    def write_page(node: PageNode, parent_dir: Path) -> None:
        slug = node.ensure_slug() or "untitled"
        page_dir = parent_dir / safe_filename(slug)
        page_dir.mkdir(parents=True, exist_ok=True)
        md_path = page_dir / f"{safe_filename(slug)}.md"

        # copy this page's assets next to it
        asset_names = set()
        if copy_assets:
            for block in _walk_blocks(node.blocks):
                local = (block.asset or {}).get("local_path")
                if not local:
                    continue
                src = Path(local)
                if not src.exists():
                    report.skipped.append(f"missing asset {local}")
                    continue
                dest = page_dir / "assets" / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(src, dest)
                asset_names.add(src.name)
                report.assets += 1

        md_path.write_text(render_page_md(node), encoding="utf-8")
        report.pages += 1
        report.files += 1
        depth = len(node.path)
        index.append("  " * depth + f"- [{node.title}]({md_path.relative_to(out).as_posix()})")

        if node.database:
            csv_path = page_dir / f"{safe_filename(slug)}-data.csv"
            _write_csv(csv_path, node.database)
            report.csv_files += 1
            index.append("  " * (depth + 1) + f"- 🗃️ data: {csv_path.relative_to(out).as_posix()}")

        for child in node.children:
            write_page(child, page_dir)

    for root in doc.pages:
        write_page(root, out)

    index_path = out / "INDEX.md"
    index_path.write_text("\n".join(index) + "\n", encoding="utf-8")
    report.files += 1
    log.info("markdown export: %s", report.summary())
    return report


def _walk_blocks(blocks: List[Block]):
    for block in blocks:
        yield block
        yield from _walk_blocks(block.children)


def _write_csv(path: Path, database: dict) -> None:
    rows = database.get("rows") or []
    fields: List[str] = list(database.get("schema") or {})
    if not fields and rows:
        fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _flatten(v) for k, v in row.items() if k in fields})


def _flatten(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value
