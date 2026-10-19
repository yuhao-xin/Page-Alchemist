"""Transform stage — make the extracted archive *yours*.

This is the stage that answers "把那些信息去除特殊标记，全部变成自己的":

* **Cleanse** — drop structural noise (table-of-contents, breadcrumbs,
  templates, AI blocks), unwrap synced blocks (keep the content, drop the
  live reference), strip annotation colours that betray the source template.
* **Icon retune** — replace source icons with a deterministic emoji chosen
  from the page slug (or keep / drop them).
* **Relayout** — demote body H1s (the page title is the H1), drop duplicate
  consecutive blocks, normalise empty paragraphs.
* **Title rewrite** — strip source branding prefixes and decorations.
* **Archive card** — prepend a generated provenance block (source URL,
  extraction time, engine, section outline) so every page carries its own
  lineage instead of looking copy-pasted.

Everything is deterministic and offline: no network, no LLM calls.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Block, Document, PageNode, RichText
from .util import get_logger, now_iso, sha1_bytes

# Structural noise that makes a copy feel like a copy.
NOISE_TYPES = {"table_of_contents", "breadcrumb", "template", "ai_block",
               "unsupported"}

# Emoji rotation for icon retune (deterministic per page slug).
RETUNE_EMOJI = [
    "📘", "📗", "📙", "📒", "📕", "📔", "📖", "🔖", "🧭", "🧪",
    "⚗️", "🔬", "🧬", "🧠", "💡", "🛠️", "📐", "🗂️", "🗃️", "🗄️",
    "📚", "🏛️", "🌱", "🔥", "🌊", "⛰️", "🌌", "🧩", "🪄", "⚙️",
]

_TITLE_PREFIXES = ("【付费】", "【VIP】", "[VIP]", "VIP", "PRO", "Premium",
                   "付费", "会员", "模板", "Template")
# Leading symbols / emoji decorations (NOT CJK: those start at U+4E00).


def _strip_leading_decor(text: str) -> str:
    """Drop leading spaces and symbol/emoji decorations from a title."""
    i = 0
    while i < len(text):
        code = ord(text[i])
        if text[i].isspace() or 0x2000 <= code <= 0x2BFF or 0x1F000 <= code <= 0x1FAFF:
            i += 1
            continue
        break
    return text[i:]


def _strip_decor(text: str) -> str:
    """Strip symbol/emoji decorations from both ends of a title."""
    stripped = _strip_leading_decor(text)
    end = len(stripped)
    while end > 0:
        code = ord(stripped[end - 1])
        if stripped[end - 1].isspace() or 0x2000 <= code <= 0x2BFF \
                or 0x1F000 <= code <= 0x1FAFF:
            end -= 1
            continue
        break
    return stripped[:end]
_BRACKET_RE = re.compile(r"^[【\[(]([^】\])]{1,20})[】\])]\s*")


def pick_emoji(seed_text: str) -> str:
    digest = sha1_bytes((seed_text or "x").encode("utf-8"))
    return RETUNE_EMOJI[int(digest[:8], 16) % len(RETUNE_EMOJI)]


# --------------------------------------------------------------------------- #
# Options & report
# --------------------------------------------------------------------------- #
@dataclass
class TransformOptions:
    drop_noise: bool = True
    strip_colors: bool = True
    icon_mode: str = "retune"          # keep | retune | none
    normalize_titles: bool = True
    demote_h1: bool = True
    dedupe: bool = True
    add_archive_card: bool = True

    def problems(self) -> List[str]:
        if self.icon_mode not in ("keep", "retune", "none"):
            return [f"icon_mode must be keep|retune|none, got {self.icon_mode!r}"]
        return []


@dataclass
class TransformReport:
    blocks_in: int = 0
    blocks_out: int = 0
    dropped: Dict[str, int] = field(default_factory=dict)
    colors_stripped: int = 0
    icons_retuned: int = 0
    titles_normalized: int = 0
    h1_demoted: int = 0
    duplicates_removed: int = 0
    cards_added: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    def summary(self) -> str:
        return (f"blocks {self.blocks_in} -> {self.blocks_out}, dropped "
                f"{sum(self.dropped.values())}, colours stripped "
                f"{self.colors_stripped}, icons retuned {self.icons_retuned}, "
                f"titles normalised {self.titles_normalized}, H1 demoted "
                f"{self.h1_demoted}, duplicates removed "
                f"{self.duplicates_removed}, archive cards {self.cards_added}")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _iter_rich_text(block: Block):
    yield from block.text
    yield from block.caption
    for cell in block.cells or []:
        yield from cell


def _dedupe(blocks: List[Block], report: TransformReport) -> List[Block]:
    out: List[Block] = []
    for block in blocks:
        if out:
            prev = out[-1]
            if (prev.type == block.type and prev.checked == block.checked
                    and prev.plain_text() == block.plain_text()
                    and block.plain_text()):
                report.duplicates_removed += 1
                continue
        out.append(block)
    return out


def _normalize_title(title: str) -> Tuple[str, bool]:
    text = (title or "").strip()
    original = text
    text = _strip_decor(text)
    changed_prefix = False
    for prefix in _TITLE_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            text = _strip_decor(text[len(prefix):])
            changed_prefix = True
            break
    match = _BRACKET_RE.match(text)
    if match and len(match.group(1)) <= 20:
        text = _strip_decor(text[match.end():])
        changed_prefix = True
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text:
        return (original or "Untitled"), False
    return text, (changed_prefix or text != original)


def _archive_card(doc: Document, node: PageNode) -> Block:
    """Generated provenance block — the "writing" half of the transform."""
    lines = [f"来源：{doc.source_url or '(unknown)'}",
             f"提取时间：{doc.extracted_at or now_iso()} · 引擎：{doc.engine}"]
    outline = [b.plain_text().strip() for b in node.blocks
               if b.type.startswith("heading") and b.plain_text().strip()]
    if outline:
        lines.append("章节：" + " / ".join(outline[:8]))
    lines.append(f"本页由 page-alchemist 归档整理（源 {len(node.blocks)} 个内容块）")
    return Block(type="callout", text=[RichText(text="\n".join(lines))],
                 raw={"_archive_card": True})


# --------------------------------------------------------------------------- #
# Transform
# --------------------------------------------------------------------------- #
def transform_document(doc: Document,
                       options: Optional[TransformOptions] = None
                       ) -> TransformReport:
    """Transform a Document in place; returns a report of what changed."""
    opts = options or TransformOptions()
    problems = opts.problems()
    if problems:
        raise ValueError("; ".join(problems))
    log = get_logger()
    report = TransformReport(blocks_in=doc.count_blocks())

    for node, _depth in doc.iter_pages():
        _transform_page(doc, node, opts, report)

    report.blocks_out = doc.count_blocks()
    doc.stats["transform"] = report.to_dict()
    log.info("transform: %s", report.summary())
    return report


def _transform_page(doc: Document, node: PageNode, opts: TransformOptions,
                    report: TransformReport) -> None:
    if opts.normalize_titles:
        new_title, changed = _normalize_title(node.title)
        if changed:
            report.titles_normalized += 1
            node.notes.append(f"title: {node.title!r} -> {new_title!r}")
            node.title = new_title
            node.ensure_slug()

    node.blocks = _cleanse_blocks(node.blocks, opts, report)

    if opts.icon_mode == "none":
        if node.icon:
            report.icons_retuned += 1
        node.icon = None
    elif opts.icon_mode == "retune":
        node.icon = pick_emoji(node.slug or node.title)
        report.icons_retuned += 1
    # "keep" leaves the source icon untouched

    if opts.add_archive_card:
        node.blocks.insert(0, _archive_card(doc, node))
        report.cards_added += 1


def _cleanse_blocks(blocks: List[Block], opts: TransformOptions,
                    report: TransformReport) -> List[Block]:
    out: List[Block] = []
    for block in blocks:
        btype = block.type
        if opts.drop_noise and btype in NOISE_TYPES:
            report.dropped[btype] = report.dropped.get(btype, 0) + 1
            continue
        if opts.drop_noise and btype == "synced_block":
            report.dropped["synced_block"] = report.dropped.get(
                "synced_block", 0) + 1
            out.extend(_cleanse_blocks(block.children, opts, report))
            continue
        if btype == "child_database":
            # the database itself is materialised separately; the inline
            # reference block is a source artefact
            report.dropped["child_database"] = report.dropped.get(
                "child_database", 0) + 1
            continue

        block.children = _cleanse_blocks(block.children, opts, report)

        if opts.strip_colors:
            for rt in _iter_rich_text(block):
                if rt.color and rt.color != "default":
                    rt.color = "default"
                    report.colors_stripped += 1

        if opts.demote_h1 and btype == "heading_1":
            block.type = "heading_2"
            report.h1_demoted += 1

        # drop blocks that carry no content at all (noise types are exempt:
        # when `drop_noise` is off the user explicitly asked to keep them)
        has_cells = any(any(cell for cell in row) for row in block.cells or [])
        if btype not in NOISE_TYPES and not block.plain_text() \
                and not has_cells and not block.children and btype not in (
                    "divider", "image", "bookmark", "embed", "child_page",
                    "child_database", "link_to_page", "table_row"):
            report.dropped[f"empty {btype}"] = report.dropped.get(
                f"empty {btype}", 0) + 1
            continue

        out.append(block)

    if opts.dedupe:
        out = _dedupe(out, report)
    return out
