"""Canonical Intermediate Representation (IR).

Everything that flows between *Extract*, *Transform* and *Publish* is expressed
with these dataclasses, so no stage ever hands another stage a raw Notion API
payload. The IR is plain JSON on disk (`structure.json` / `transformed.json`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .util import slugify


# --------------------------------------------------------------------------- #
# Rich text
# --------------------------------------------------------------------------- #
@dataclass
class RichText:
    text: str = ""
    kind: str = "text"  # text | mention | equation
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    underline: bool = False
    code: bool = False
    color: str = "default"
    link: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RichText":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    type: str = "paragraph"
    text: List[RichText] = field(default_factory=list)
    children: List["Block"] = field(default_factory=list)
    checked: Optional[bool] = None
    language: Optional[str] = None
    url: Optional[str] = None
    caption: List[RichText] = field(default_factory=list)
    cells: List[List[RichText]] = field(default_factory=list)  # table_row cells
    asset: Optional[Dict[str, Any]] = None  # {"name","url","kind","local_path"}
    raw: Dict[str, Any] = field(default_factory=dict)  # original Notion block

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        d = dict(d or {})
        d["text"] = [RichText.from_dict(x) for x in d.get("text", [])]
        d["caption"] = [RichText.from_dict(x) for x in d.get("caption", [])]
        d["cells"] = [[RichText.from_dict(x) for x in cell]
                      for cell in d.get("cells", [])]
        d["children"] = [Block.from_dict(x) for x in d.get("children", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def plain_text(self) -> str:
        return "".join(rt.text for rt in self.text)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@dataclass
class PageNode:
    source_id: str = ""
    title: str = "Untitled"
    icon: Optional[str] = None          # emoji or external URL
    cover: Optional[str] = None         # external URL
    blocks: List[Block] = field(default_factory=list)
    children: List["PageNode"] = field(default_factory=list)
    database: Optional[Dict[str, Any]] = None  # {"schema": {...}, "rows": [...]}
    properties: Dict[str, Any] = field(default_factory=dict)
    path: List[str] = field(default_factory=list)  # breadcrumb titles
    slug: str = ""
    notes: List[str] = field(default_factory=list)  # e.g. "database exported as CSV"

    def ensure_slug(self) -> str:
        if not self.slug:
            self.slug = slugify(self.title) or "untitled"
        return self.slug

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PageNode":
        d = dict(d or {})
        d["blocks"] = [Block.from_dict(x) for x in d.get("blocks", [])]
        d["children"] = [PageNode.from_dict(x) for x in d.get("children", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------- #
# Document (archive root)
# --------------------------------------------------------------------------- #
@dataclass
class Document:
    source_url: str = ""
    engine: str = "api"
    extracted_at: str = ""
    pages: List[PageNode] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def iter_pages(self, node: Optional[PageNode] = None, _depth: int = 0):
        """Depth-first iteration over every page in the archive."""
        for page in (self.pages if node is None else [node]):
            yield page, _depth
            for child in page.children:
                yield from self.iter_pages(child, _depth + 1)

    def count_blocks(self) -> int:
        # iter_pages() already walks the whole tree (parent -> children);
        # summing len(page.blocks) per yielded page avoids double counting.
        return sum(len(page.blocks) for page, _ in self.iter_pages())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Document":
        d = dict(d or {})
        d["pages"] = [PageNode.from_dict(x) for x in d.get("pages", [])]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})
