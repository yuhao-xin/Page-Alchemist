"""Official Notion API engine — write an IR document back into Notion.

Design notes
------------
* **Flat appends.** A page is created empty (``POST /v1/pages``) and filled
  with ``PATCH /v1/blocks/{id}/children``. Every append carries at most 100
  children and stays well under the 500 KB body cap. We deliberately never
  nest children inside a payload: the append response returns the ids of the
  blocks it committed, so nested content is appended level-by-level against
  those ids. That sidesteps the "two levels of nesting per request" limit
  entirely and is unambiguous about where ``children`` belongs.
* **Sequential writes.** Appends to the same parent are strictly sequential —
  parallel writes produce unpredictable ordering.
* **Idempotency / resume.** Every write is recorded in ``.na_state.json``:
  source id -> created page id, how many top-level units were appended, the
  ids of units that have children, and which of those children are done.
  Re-running resumes instead of duplicating; on resume the recorded offset is
  reconciled against the live child count of the page.
* **503 handling.** ``retry_guidance: do_not_retry`` means the write landed —
  ``NotionClient._request`` surfaces the body instead of replaying, so a
  landed write is never duplicated.
* **Files.** Local assets are re-uploaded via ``POST /v1/file_uploads``
  (Notion-hosted file URLs are signed and expire); on failure we fall back to
  the original external URL.
* **Special markers.** ``synced_block`` references, table-of-contents,
  breadcrumbs, templates and AI blocks are structural noise that makes a copy
  feel like a copy — they are dropped (synced blocks are unwrapped so their
  *content* survives).
"""
from __future__ import annotations

import json
import mimetypes
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Block, Document, PageNode, RichText
from .notion_api import API_BASE, NOTION_VERSION, NotionApiError, NotionClient
from .util import get_logger, now_iso

# --------------------------------------------------------------------------- #
# Hard limits (developers.notion.com/reference/request-limits)
# --------------------------------------------------------------------------- #
MAX_APPEND = 100            # children per append request
MAX_BODY_BYTES = 400_000    # stay under the 500 KB body cap
RICH_TEXT_LIMIT = 2000      # chars per rich text object

# Structural noise that makes a copy feel like a copy — dropped on publish.
_DROP_TYPES = {"table_of_contents", "breadcrumb", "template", "ai_block",
               "unsupported"}

# Notion code-block languages (anything else falls back to "plain text" so the
# API never rejects the payload).
_CODE_LANGUAGES = {
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++",
    "c#", "css", "dart", "diff", "docker", "elixir", "elm", "erlang", "flow",
    "fortran", "f#", "gherkin", "glsl", "go", "graphql", "groovy", "haskell",
    "html", "http", "java", "javascript", "json", "julia", "kotlin", "latex",
    "less", "lisp", "livescript", "lua", "makefile", "markdown", "markup",
    "matlab", "mermaid", "nix", "objective-c", "ocaml", "pascal", "perl",
    "php", "plain text", "powershell", "prolog", "protobuf", "python", "r",
    "reason", "ruby", "rust", "sass", "scala", "scheme", "scss", "shell",
    "sql", "stylus", "swift", "toml", "typescript", "vb.net", "verilog",
    "vhdl", "visual basic", "webassembly", "xml", "yaml",
}

# A unit is (position, payload, children-to-append-to-the-created-block-id).
Unit = Tuple[int, Dict[str, Any], List[Block]]


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class PublishReport:
    pages_created: int = 0
    pages_reused: int = 0
    blocks_appended: int = 0
    databases_created: int = 0
    rows_inserted: int = 0
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        return (f"pages: {self.pages_created} created / {self.pages_reused} "
                f"resumed, blocks appended: {self.blocks_appended}, databases: "
                f"{self.databases_created}, rows: {self.rows_inserted}, "
                f"skipped: {len(self.skipped)}, errors: {len(self.errors)}")


# --------------------------------------------------------------------------- #
# State store (.na_state.json)
# --------------------------------------------------------------------------- #
class StateStore:
    """Durable write state so an interrupted run can resume without duplicates."""

    VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, Any] = {
            "version": self.VERSION,
            "pages": {},
            "databases": {},
            "created_at": now_iso(),
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "pages" in loaded:
                self.data = loaded
        except Exception as exc:  # noqa: BLE001 - corrupt state must not kill the run
            get_logger().warning("ignoring corrupt state file %s (%s)",
                                 self.path, exc)

    def save(self) -> None:
        self.data["updated_at"] = now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)

    # -- pages ---------------------------------------------------------- #
    def page_entry(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.data["pages"].get(source_id) if source_id else None

    def set_page(self, source_id: str, **fields: Any) -> Dict[str, Any]:
        if not source_id:
            return {}
        entry = self.data["pages"].setdefault(source_id, {})
        entry.update(fields)
        entry.setdefault("created_at", now_iso())
        self.save()
        return entry

    # -- databases ------------------------------------------------------ #
    def db_entry(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.data["databases"].get(source_id) if source_id else None

    def set_db(self, source_id: str, **fields: Any) -> Dict[str, Any]:
        if not source_id:
            return {}
        entry = self.data["databases"].setdefault(source_id, {})
        entry.update(fields)
        entry.setdefault("created_at", now_iso())
        self.save()
        return entry


# --------------------------------------------------------------------------- #
# Helpers (pure functions — unit tested)
# --------------------------------------------------------------------------- #
def _is_emoji(text: str) -> bool:
    return bool(text) and all(ord(ch) >= 0x2000 for ch in text[:2])


def _split_runs(text: str, limit: int = RICH_TEXT_LIMIT) -> List[str]:
    if len(text) <= limit:
        return [text]
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def rich_text_payload(items: List[RichText]) -> List[Dict[str, Any]]:
    """IR rich text -> Notion rich text array (runs longer than 2000 chars
    are split so no content is silently dropped)."""
    out: List[Dict[str, Any]] = []
    for rt in items or []:
        if rt.kind == "equation":
            out.append({"type": "equation",
                        "equation": {"expression": (rt.text or " ")[:RICH_TEXT_LIMIT]}})
            continue
        if not rt.text:
            continue
        for chunk in _split_runs(rt.text):
            node: Dict[str, Any] = {"type": "text", "text": {"content": chunk}}
            if rt.link:
                node["text"]["link"] = {"url": rt.link}
            annotations: Dict[str, Any] = {}
            if rt.bold:
                annotations["bold"] = True
            if rt.italic:
                annotations["italic"] = True
            if rt.strikethrough:
                annotations["strikethrough"] = True
            if rt.underline:
                annotations["underline"] = True
            if rt.code:
                annotations["code"] = True
            if annotations:
                node["annotations"] = annotations
            out.append(node)
    return out


def _payload_bytes(payload: Dict[str, Any]) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def _chunks(units: List[Unit]) -> List[List[Unit]]:
    """Split units into request-sized chunks (<= 100 children, < 500 KB)."""
    chunks: List[List[Unit]] = []
    chunk: List[Unit] = []
    size = 0
    for unit in units:
        p_size = _payload_bytes(unit[1])
        if chunk and (len(chunk) >= MAX_APPEND or size + p_size > MAX_BODY_BYTES):
            chunks.append(chunk)
            chunk, size = [], 0
        chunk.append(unit)
        size += p_size
    if chunk:
        chunks.append(chunk)
    return chunks


# --------------------------------------------------------------------------- #
# Publisher
# --------------------------------------------------------------------------- #
class NotionPublisher:
    """Writes an IR `Document` into the user's own Notion workspace."""

    def __init__(self, settings, *, client: Optional[NotionClient] = None,
                 dry_run: bool = False, upload_files: bool = True):
        self.s = settings
        self.log = get_logger()
        self._client = client          # created lazily: --dry-run needs no I/O
        self.dry_run = dry_run
        self.upload_files = upload_files
        self.state = StateStore(Path(settings.state_dir) / ".na_state.json")
        self.report = PublishReport()
        self._active: set = set()
        self._dry_seq = 0
        self._skipped_seen: set = set()

    @property
    def client(self) -> NotionClient:
        if self._client is None:
            self._client = NotionClient(self.s)
        return self._client

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #
    def publish(self, doc: Document, parent_page_id: str) -> PublishReport:
        self.state.data["source_url"] = doc.source_url
        self.state.data["target_parent"] = parent_page_id
        try:
            for root in doc.pages:
                self._publish_page(root, parent_page_id)
        except KeyboardInterrupt:
            self.state.save()
            self.log.warning("interrupted — state saved; re-run the same "
                             "command to resume")
            raise
        self.state.save()
        self.log.info("publish finished: %s", self.report.summary())
        return self.report

    # ------------------------------------------------------------------ #
    # Pages
    # ------------------------------------------------------------------ #
    def _publish_page(self, node: PageNode, parent_id: str, depth: int = 0) -> None:
        if node.source_id and node.source_id in self._active:
            self._skip(f"cycle guard: {node.title}")
            return
        self._active.add(node.source_id)
        try:
            entry = self.state.page_entry(node.source_id)
            if entry and entry.get("page_id"):
                page_id = entry["page_id"]
                self.report.pages_reused += 1
                offset = self._resume_offset(node, page_id, entry)
                self.log.info("resume  %s%s (%d/%d units)", node.title,
                              f" [{depth}]" if depth else "", offset,
                              len(self._units(node.blocks)))
            else:
                page_id = self._create_page(node, parent_id, depth)
                offset = 0
            self._fill_page(node, page_id, offset, entry)
            for child in node.children:
                self._publish_page(child, page_id, depth + 1)
            if node.database:
                self._publish_database(node, page_id)
        finally:
            self._active.discard(node.source_id)

    def _create_page(self, node: PageNode, parent_id: str, depth: int) -> str:
        title = (node.title or "Untitled")[:RICH_TEXT_LIMIT]
        payload: Dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "properties": {"title": {"title": [{"type": "text",
                                                "text": {"content": title}}]}},
        }
        icon = self._icon_payload(node)
        if icon:
            payload["icon"] = icon
        cover = self._cover_payload(node)
        if cover:
            payload["cover"] = cover

        if self.dry_run:
            self._dry_seq += 1
            page_id = f"dry-page-{self._dry_seq}"
            self.report.pages_created += 1
            self.report.actions.append({
                "op": "create_page", "title": node.title, "parent": parent_id,
                "icon": (icon or {}).get("emoji") if icon else None,
                "blocks": self._count_units(node.blocks),
                "subpages": len(node.children), "database": bool(node.database),
            })
            self.state.set_page(node.source_id, page_id=page_id, title=node.title,
                                path=node.path + [node.title],
                                units_appended=0, dry_run=True)
            return page_id

        try:
            resp = self.client._request("POST", "/pages", json_body=payload)
        except NotionApiError as exc:
            if "icon" in payload or "cover" in payload:
                # signed / expired media is the usual culprit — retry bare
                self.log.warning("page create with media failed (%s); retrying "
                                 "without icon/cover", str(exc)[:160])
                payload.pop("icon", None)
                payload.pop("cover", None)
                resp = self.client._request("POST", "/pages", json_body=payload)
            else:
                raise
        page_id = resp["id"]
        self.report.pages_created += 1
        self.state.set_page(node.source_id, page_id=page_id, title=node.title,
                            path=node.path + [node.title], units_appended=0)
        self.log.info("create  %s%s -> %s", node.title,
                      f" [{depth}]" if depth else "", page_id)
        return page_id

    def _resume_offset(self, node: PageNode, page_id: str,
                       entry: Dict[str, Any]) -> int:
        """Reconcile the recorded unit offset against the live child count."""
        recorded = int(entry.get("units_appended", 0) or 0)
        total = len(self._units(node.blocks))
        if self.dry_run or recorded >= total:
            return recorded
        try:
            counted = sum(1 for _ in self.client.iter_block_children(page_id))
        except NotionApiError as exc:
            self.log.warning("resume count failed for %r (%s); trusting state",
                             node.title, str(exc)[:120])
            return recorded
        # a materialised database is also a child block of the page
        if node.database and self.state.db_entry(f"{node.source_id}::db"):
            counted -= 1
        inferred = min(max(counted, 0), total)
        if inferred != recorded:
            self.log.warning("resume %r: state says %d units, page has %d "
                             "-> continuing at %d", node.title, recorded,
                             counted, max(recorded, inferred))
        return max(recorded, inferred)

    # ------------------------------------------------------------------ #
    # Filling a page
    # ------------------------------------------------------------------ #
    def _fill_page(self, node: PageNode, page_id: str, offset: int,
                   entry: Optional[Dict[str, Any]]) -> None:
        units = self._units(node.blocks)
        if self.dry_run:
            self.report.blocks_appended += len(units) - offset
            self.report.actions.append({"op": "append_blocks", "page": node.title,
                                        "count": max(len(units) - offset, 0)})
            return

        kids_done = {int(k) for k in (entry.get("kids_done") or {})} if entry else set()
        done = offset
        for chunk in _chunks(units[offset:]):
            ids = self._append_units(page_id, chunk)
            for unit, bid in zip(chunk, ids):
                pos, _payload, kids = unit
                if kids and bid and pos not in kids_done:
                    if entry is not None:
                        entry.setdefault("block_ids", {})[str(pos)] = bid
                    self._append_kids(bid, kids)
                    if entry is not None:
                        entry.setdefault("kids_done", {})[str(pos)] = True
            done = chunk[-1][0] + 1
            if entry is not None:
                self.state.set_page(
                    node.source_id, units_appended=done,
                    block_ids=entry.get("block_ids") or {},
                    kids_done=entry.get("kids_done") or {})
            else:
                self.state.save()
            self.log.info("append  %r: %d blocks (%d/%d units)", node.title,
                          len(chunk), done, len(units))
        self._finish_kids(node, entry, done)

    def _finish_kids(self, node: PageNode, entry: Optional[Dict[str, Any]],
                     done: int) -> None:
        """Complete nested children for units written before an interruption."""
        if entry is None or self.dry_run:
            return
        kids_done = {int(k) for k in (entry.get("kids_done") or {})}
        block_ids = entry.get("block_ids") or {}
        units = {pos: kids for pos, _payload, kids in self._units(node.blocks)}
        for pos in range(done):
            if pos in kids_done:
                continue
            kids = units.get(pos) or []
            if not kids:
                continue
            bid = block_ids.get(str(pos))
            if not bid:
                self.log.warning("cannot finish nested children of unit #%d "
                                 "in %r (block id unknown)", pos, node.title)
                continue
            self.log.info("finishing nested children of unit #%d in %r", pos,
                          node.title)
            self._append_kids(bid, kids)
            entry.setdefault("kids_done", {})[str(pos)] = True
            self.state.set_page(node.source_id,
                                kids_done=entry.get("kids_done") or {})

    def _append_kids(self, block_id: str, kids: List[Block]) -> None:
        """Append children under a block id, recursively (any depth)."""
        units = self._units(kids)
        if not units:
            return
        for chunk in _chunks(units):
            ids = self._append_units(block_id, chunk)
            for (_pos, _payload, sub_kids), sub_id in zip(chunk, ids):
                if sub_kids and sub_id:
                    self._append_kids(sub_id, sub_kids)

    def _append_units(self, parent_id: str, units: List[Unit]
                      ) -> List[Optional[str]]:
        """Append units (chunked) and return the created ids, aligned."""
        out: List[Optional[str]] = []
        for chunk in _chunks(units):
            out.extend(self._append_chunk(parent_id, [u[1] for u in chunk]))
            self.report.blocks_appended += len(chunk)
        return out

    def _append_chunk(self, parent_id: str,
                      payloads: List[Dict[str, Any]]) -> List[Optional[str]]:
        """Append one request's worth of blocks; isolate failures by splitting."""
        if not payloads:
            return []
        try:
            resp = self.client._request(
                "PATCH", f"/blocks/{parent_id}/children",
                json_body={"children": payloads})
            results = resp.get("results") or []
            ids = [r.get("id") for r in results if isinstance(r, dict)]
            if len(ids) < len(payloads):
                ids += [None] * (len(payloads) - len(ids))
            return ids[:len(payloads)]
        except NotionApiError as exc:
            if len(payloads) == 1:
                self._skip(f"block append failed: {str(exc)[:160]}")
                return [None]
            self.log.warning("chunk of %d failed (%s) — splitting to isolate",
                             len(payloads), str(exc)[:160])
            mid = len(payloads) // 2
            return (self._append_chunk(parent_id, payloads[:mid])
                    + self._append_chunk(parent_id, payloads[mid:]))

    # ------------------------------------------------------------------ #
    # IR -> flat Notion payloads
    # ------------------------------------------------------------------ #
    def _units(self, blocks: List[Block]) -> List[Unit]:
        """Flatten IR blocks into appendable units (position, payload, kids)."""
        out: List[Unit] = []
        pos = 0
        for blk in blocks:
            for payload, kids in self._flat_units(blk):
                out.append((pos, payload, kids))
                pos += 1
        return out

    def _flat_units(self, block: Block) -> List[Tuple[Dict[str, Any], List[Block]]]:
        """One IR block -> [(payload, children-to-append-to-created-id)].

        A ``synced_block`` is unwrapped into its children; a ``column_list``
        coerces every child into a column; a ``table`` pads its rows to the
        table width.
        """
        t = block.type
        if t in _DROP_TYPES:
            self._skip(self._drop_note(block))
            return []
        if t == "child_database":
            return []  # materialised separately as a real database
        if t == "synced_block":
            out: List[Tuple[Dict[str, Any], List[Block]]] = []
            for kid in block.children:
                out.extend(self._flat_units(kid))
            return out
        if t == "column_list":
            columns: List[Block] = []
            for kid in block.children:
                if kid.type == "column":
                    columns.append(kid)
                elif kid.type in _DROP_TYPES or kid.type == "child_database":
                    continue
                else:
                    columns.append(Block(type="column", children=[kid]))
            if not columns:
                self._skip("column_list: empty")
                return []
            return [({"type": "column_list", "column_list": {}}, columns)]
        if t == "table":
            rows = [c for c in block.children if c.type == "table_row"]
            width = (block.raw.get("table") or {}).get("table_width")
            if not width:
                width = max((len(c.cells) for c in rows), default=0)
            if not rows or not width:
                self._skip("table: empty")
                return []
            padded = [replace(r, cells=(list(r.cells) + [[]] * width)[:width])
                      for r in rows]
            return [({"type": "table",
                      "table": {"table_width": width, "has_column_header": True,
                                "has_row_header": False}}, padded)]

        payload = self._base_payload(block)
        if payload is None:
            return []
        return [(payload, list(block.children))]

    def _base_payload(self, block: Block) -> Optional[Dict[str, Any]]:
        """One flat Notion block payload (no children); None = drop."""
        t = block.type
        rt = rich_text_payload(block.text)

        if t == "paragraph":
            return {"type": "paragraph", "paragraph": {"rich_text": rt}}
        if t in ("heading_1", "heading_2", "heading_3"):
            return {"type": t, t: {"rich_text": rt}}
        if t in ("bulleted_list_item", "numbered_list_item", "toggle"):
            return {"type": t, t: {"rich_text": rt}}
        if t == "to_do":
            return {"type": t, t: {"rich_text": rt, "checked": bool(block.checked)}}
        if t == "code":
            lang = (block.language or "plain text").lower()
            if lang not in _CODE_LANGUAGES:
                lang = "plain text"
            return {"type": "code", "code": {"rich_text": rt, "language": lang}}
        if t == "quote":
            return {"type": "quote", "quote": {"rich_text": rt}}
        if t == "callout":
            return {"type": "callout",
                    "callout": {"rich_text": rt,
                                "icon": {"type": "emoji", "emoji": "💡"}}}
        if t == "divider":
            return {"type": "divider", "divider": {}}
        if t in ("image", "video", "pdf", "file"):
            file_payload = self._file_payload(block)
            return {"type": t, t: file_payload} if file_payload else None
        if t in ("bookmark", "embed", "link_preview"):
            if not block.url:
                self._skip(f"{t}: missing url")
                return None
            return {"type": "bookmark", "bookmark": {"url": block.url}}
        if t in ("child_page", "child_database"):
            title = block.plain_text() or "Untitled"
            mark = "📄" if t == "child_page" else "🗃️"
            return {"type": "paragraph",
                    "paragraph": {"rich_text": rich_text_payload(
                        [RichText(text=f"{mark} {title}")])}}
        if t == "link_to_page":
            ref = block.plain_text() or "linked page"
            return {"type": "paragraph",
                    "paragraph": {"rich_text": rich_text_payload(
                        [RichText(text=f"🔗 {ref}", italic=True)])}}
        if t == "table_row":
            cells = [rich_text_payload(cell) for cell in (block.cells or [])]
            if not any(cells):
                self._skip("table_row: empty")
                return None
            return {"type": "table_row", "table_row": {"cells": cells}}
        if t == "column":
            return {"type": "column", "column": {}}

        # Unknown block type — keep the text, drop the exotic structure.
        if block.plain_text():
            self._skip(f"unknown type {t!r} -> paragraph")
            return {"type": "paragraph", "paragraph": {"rich_text": rt}}
        self._skip(f"unknown empty type {t!r}")
        return None

    def _count_units(self, blocks: List[Block]) -> int:
        """Total appendable payloads including nested children (dry-run)."""
        total = 0
        for blk in blocks:
            for _payload, kids in self._flat_units(blk):
                total += 1 + self._count_units(kids)
        return total

    def _file_payload(self, block: Block) -> Optional[Dict[str, Any]]:
        asset = block.asset or {}
        local = asset.get("local_path")
        if self.upload_files and local and not self.dry_run:
            path = Path(local)
            if path.exists():
                file_id = self.upload_file(path)
                if file_id:
                    return {"type": "file_upload", "file_upload": {"id": file_id}}
                self.log.warning("upload failed for %s — falling back to URL",
                                 path.name)
        if block.url:
            return {"type": "external", "external": {"url": block.url}}
        self._skip(f"{block.type}: no accessible file")
        return None

    # ------------------------------------------------------------------ #
    # Databases
    # ------------------------------------------------------------------ #
    def _publish_database(self, node: PageNode, page_id: str) -> None:
        db = node.database or {}
        schema = db.get("raw_schema") or {}
        rows = db.get("rows") or []
        title = "Database"
        for blk in node.blocks:
            if blk.type == "child_database":
                title = blk.plain_text() or "Database"
                break
        source_id = f"{node.source_id}::db"
        entry = self.state.db_entry(source_id)

        if entry and entry.get("database_id"):
            database_id = entry["database_id"]
        elif self.dry_run:
            self._dry_seq += 1
            database_id = f"dry-db-{self._dry_seq}"
            self.report.actions.append({"op": "create_database", "title": title,
                                        "rows": len(rows)})
            self.report.databases_created += 1
            self.state.set_db(source_id, database_id=database_id, title=title,
                              rows_done=0, dry_run=True)
        else:
            payload = {
                "parent": {"type": "page_id", "page_id": page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": self._db_properties(schema),
            }
            try:
                resp = self.client._request("POST", "/databases",
                                            json_body=payload)
            except NotionApiError as exc:
                self.report.errors.append(f"database '{title}': {str(exc)[:200]}")
                return
            database_id = resp["id"]
            self.report.databases_created += 1
            self.state.set_db(source_id, database_id=database_id, title=title,
                              rows_done=0)
            self.log.info("create  database %r -> %s", title, database_id)

        start = int((entry or {}).get("rows_done", 0) or 0) if entry else 0
        title_name = next((n for n, spec in schema.items()
                           if spec.get("type") == "title"), None)
        for i in range(start, len(rows)):
            if self.dry_run:
                self.report.rows_inserted += 1
                continue
            props = self._row_properties(rows[i], schema, title_name)
            try:
                self.client._request("POST", "/pages", json_body={
                    "parent": {"type": "database_id",
                               "database_id": database_id},
                    "properties": props,
                })
            except NotionApiError as exc:
                self.report.errors.append(
                    f"row {i} of '{title}': {str(exc)[:200]}")
                continue
            self.report.rows_inserted += 1
            if i % 10 == 0 or i == len(rows) - 1:
                self.state.set_db(source_id, rows_done=i + 1)
        if not self.dry_run and rows:
            self.state.set_db(source_id, rows_done=len(rows))

    @staticmethod
    def _db_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, spec in schema.items():
            ptype = spec.get("type")
            if ptype == "title":
                out[name] = {"title": {}}
            elif ptype in ("rich_text", "url", "email", "phone_number",
                           "number", "checkbox", "date"):
                out[name] = {ptype: {}}
            elif ptype == "select":
                out[name] = {"select": {"options":
                                        (spec.get("select") or {}).get("options", [])}}
            elif ptype == "multi_select":
                out[name] = {"multi_select": {"options":
                                              (spec.get("multi_select") or {}).get("options", [])}}
            else:
                out[name] = {"rich_text": {}}
        if not any("title" in v for v in out.values()):
            out["Name"] = {"title": {}}
        return out

    @staticmethod
    def _row_properties(row: Dict[str, Any], schema: Dict[str, Any],
                        title_name: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        def text(value: Any) -> List[Dict[str, Any]]:
            return [{"type": "text",
                     "text": {"content": str(value)[:RICH_TEXT_LIMIT]}}]

        for name, value in row.items():
            ptype = schema.get(name)
            if value is None or value == "":
                continue
            if ptype == "title" or (title_name and name == title_name):
                out[name] = {"title": text(value)}
            elif ptype == "rich_text":
                out[name] = {"rich_text": text(value)}
            elif ptype == "number":
                out[name] = {"number": value if isinstance(value, (int, float)) else None}
            elif ptype == "select":
                out[name] = {"select": {"name": str(value)}}
            elif ptype == "multi_select":
                out[name] = {"multi_select": [{"name": str(v)} for v in value]}
            elif ptype == "date":
                out[name] = {"date": {"start": str(value)}}
            elif ptype == "checkbox":
                out[name] = {"checkbox": bool(value)}
            elif ptype in ("url", "email", "phone_number"):
                out[name] = {ptype: str(value)}
            else:
                out[name] = {"rich_text": text(value)}
        if title_name and title_name not in out:
            out[title_name] = {"title": text("Untitled")}
        return out

    # ------------------------------------------------------------------ #
    # Icons / covers / files
    # ------------------------------------------------------------------ #
    def _icon_payload(self, node: PageNode) -> Optional[Dict[str, Any]]:
        # The icon policy (keep / retune / none) lives in the Transform stage;
        # by the time we get here `node.icon` is already final.
        if node.icon and _is_emoji(node.icon):
            return {"type": "emoji", "emoji": node.icon}
        return None

    @staticmethod
    def _cover_payload(node: PageNode) -> Optional[Dict[str, Any]]:
        # Notion cover urls are signed and expire — not worth carrying over.
        return None

    def upload_file(self, path: Path) -> Optional[str]:
        """Upload a local asset via POST /v1/file_uploads; return its id."""
        import requests  # local import keeps --help fast

        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            self.client.limiter.wait()
            with open(path, "rb") as fh:
                resp = requests.post(
                    API_BASE + "/file_uploads",
                    files={"file": (path.name, fh, ctype)},
                    headers={
                        "Authorization": f"Bearer {self.s.notion_token}",
                        "Notion-Version": NOTION_VERSION,
                    },
                    timeout=max(self.s.http_timeout, 120),
                )
            if resp.status_code >= 400:
                self.log.warning("file upload failed %s: %s", path.name,
                                 resp.text[:200])
                return None
            file_id = (resp.json() or {}).get("id")
            self.client.stats["files_uploaded"] = \
                self.client.stats.get("files_uploaded", 0) + 1
            return file_id
        except Exception as exc:  # noqa: BLE001 - upload is best-effort
            self.log.warning("file upload error %s: %s", path.name, exc)
            return None

    # ------------------------------------------------------------------ #
    def _skip(self, message: str) -> None:
        if message not in self._skipped_seen:
            self._skipped_seen.add(message)
            self.report.skipped.append(message)

    @staticmethod
    def _drop_note(block: Block) -> str:
        text = block.plain_text()[:40]
        return f"{block.type}: {text!r}" if text else str(block.type)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def publish_document(doc: Document, settings, *,
                     parent_page_id: Optional[str] = None,
                     dry_run: bool = False,
                     upload_files: bool = True) -> PublishReport:
    """Write a (transformed) IR document into the user's own Notion."""
    from .util import extract_notion_id

    parent = (parent_page_id or settings.parent_page or "").strip()
    if not parent:
        raise ValueError(
            "no parent page given. Pass parent_page_id=... or set "
            "NA_PARENT_PAGE — pages cannot be created at the workspace root.")
    # feed the resolved parent back so validation below sees it
    settings.parent_page = parent
    problems = settings.problems(need_token=not dry_run, need_parent=True)
    if problems:
        raise ValueError("; ".join(problems))
    parent_id = extract_notion_id(parent)
    publisher = NotionPublisher(settings, dry_run=dry_run,
                                upload_files=upload_files)
    return publisher.publish(doc, parent_id)
