"""Feishu / Lark publish engine — copy the IR into Feishu Docs (docx).

Design notes
------------
* **Auth.** ``app_id`` + ``app_secret`` exchange for a
  ``tenant_access_token`` (cached until shortly before expiry, refreshed
  transparently on 401 / token errors).
* **Shape.** One IR page becomes one Feishu docx *document*: Feishu has no
  API to nest a document inside another document, so sub-pages are created
  as sibling documents under the same folder and the hierarchy is preserved
  as a breadcrumb callout on each page.
* **Writes.** Blocks go out through the ``descendant`` batch API (at most
  100 blocks per request). Each block carries a caller-chosen temporary
  ``block_id`` and a ``children`` list, which expresses nesting in one
  round-trip instead of the level-by-level dance Notion requires.
* **Idempotency / resume.** ``.na_feishu_state.json`` maps source page id
  -> document id, so a re-run reuses documents instead of duplicating them.
  A document that was created but never filled (``units == 0``) is re-filled
  in place on the next run.
* **Rate limiting** follows the Notion writer's conventions: a minimum
  interval plus ``Retry-After`` honoured on 429.
* **Files.** Local assets are uploaded via
  ``/open-apis/drive/v1/medias/upload_all`` (``parent_type=docx_image``).
  Feishu cannot hot-link an external image into a docx block, so remote
  images without a local copy degrade to a link paragraph.

Block type numbers follow Feishu's ``BlockType`` enum; code-block language
ids follow the documented ``CodeLanguage`` enum (anything unlisted degrades
to ``PlainText`` — a cosmetic fallback, never a request failure).
"""
from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .models import Block, Document, PageNode, RichText
from .util import RateLimiter, backoff_delay, get_logger, now_iso, slugify

FEISHU_BASE = "https://open.feishu.cn"
LARK_BASE = "https://open.larksuite.com"

MAX_BLOCKS_PER_REQUEST = 100   # Feishu caps descendant at 200; 100 is safer
MAX_TABLE_CELLS = 400          # tables above this degrade to text lines
MAX_TABLE_COLUMNS = 20
MAX_DB_ROWS = 200              # database rows rendered into a table
STATE_FILENAME = ".na_feishu_state.json"

# --------------------------------------------------------------------------- #
# Feishu docx BlockType numbers
# --------------------------------------------------------------------------- #
T_TEXT = 2
T_H1 = 3
T_H2 = 4
T_H3 = 5
T_H4 = 6
T_BULLET = 12
T_ORDERED = 13
T_CODE = 14
T_QUOTE = 15
T_TODO = 17
T_CALLOUT = 19
T_DIVIDER = 22
T_IMAGE = 27
T_TABLE = 31
T_TABLE_CELL = 32

# block_type -> the body field name Feishu expects for it
_BODY_KEY = {
    T_TEXT: "text", T_H1: "heading1", T_H2: "heading2", T_H3: "heading3",
    T_H4: "heading4", T_BULLET: "bullet", T_ORDERED: "ordered",
    T_CODE: "code", T_QUOTE: "quote", T_TODO: "todo", T_CALLOUT: "callout",
    T_DIVIDER: "divider", T_IMAGE: "image", T_TABLE: "table",
    T_TABLE_CELL: "table_cell",
}

# Notion IR block type -> Feishu block_type (unmapped types degrade to text)
_IR_TO_FEISHU = {
    "paragraph": T_TEXT,
    "heading_1": T_H1,
    "heading_2": T_H2,
    "heading_3": T_H3,
    "heading_4": T_H4,
    "bulleted_list_item": T_BULLET,
    "numbered_list_item": T_ORDERED,
    "to_do": T_TODO,
    "code": T_CODE,
    "quote": T_QUOTE,
    "callout": T_CALLOUT,
    "divider": T_DIVIDER,
}

# Feishu CodeLanguage enum (subset); unknown languages -> PlainText (1).
_CODE_LANG = {
    "bash": 7, "shell": 56, "c": 10, "c++": 9, "cpp": 9, "c#": 8,
    "csharp": 8, "css": 12, "dockerfile": 18, "go": 22, "html": 24,
    "http": 26, "java": 29, "javascript": 30, "js": 30, "json": 28,
    "kotlin": 32, "latex": 33, "lua": 35, "makefile": 37, "markdown": 38,
    "md": 38, "nginx": 39, "objective-c": 40, "php": 41, "powershell": 44,
    "python": 47, "r": 48, "ruby": 50, "rust": 51, "scala": 53,
    "swift": 57, "typescript": 59, "ts": 59, "xml": 62, "yaml": 63,
    "yml": 63,
}

# Structural noise / structures handled elsewhere — never emitted as blocks.
_SKIP_TYPES = {"table_of_contents", "breadcrumb", "template", "ai_block",
               "unsupported", "child_page", "child_database", "link_to_page",
               "embed"}

# Feishu app-level codes meaning "the tenant token is dead — refresh it".
_TOKEN_ERROR_CODES = {99991661, 99991663, 99991664}


class FeishuApiError(RuntimeError):
    """Raised for non-retryable Feishu API failures."""


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class FeishuPublishReport:
    documents_total: int = 0
    documents_created: int = 0
    documents_reused: int = 0
    documents_refilled: int = 0
    blocks_total: int = 0
    images_uploaded: int = 0
    documents: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    finished_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        return (f"documents    : {self.documents_created} created, "
                f"{self.documents_refilled} re-filled, "
                f"{self.documents_reused} reused "
                f"(of {self.documents_total})\n"
                f"blocks       : {self.blocks_total}\n"
                f"images       : {self.images_uploaded} uploaded\n"
                f"errors       : {len(self.errors)}")


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #
class FeishuClient:
    """Minimal Feishu Open API client: token auth + JSON requests."""

    def __init__(self, settings: Settings, *, session=None,
                 base: Optional[str] = None):
        import requests  # local import keeps `--help` fast

        self.s = settings
        self._requests = requests
        self.base = (base or settings.feishu_base or FEISHU_BASE).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.limiter = RateLimiter(max(1.0, settings.max_rps))
        self.log = get_logger()
        self._token = ""
        self._token_expiry = 0.0  # time.monotonic() deadline

    # ------------------------------------------------------------------ #
    # auth
    # ------------------------------------------------------------------ #
    def tenant_access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        data = self._request(
            "POST", "/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": self.s.feishu_app_id,
                       "app_secret": self.s.feishu_app_secret},
            auth=False)
        token = data.get("tenant_access_token") or ""
        if not token:
            raise FeishuApiError(
                f"tenant_access_token missing in auth response: "
                f"{str(data)[:200]}")
        self._token = token
        expire = float(data.get("expire", 7200) or 7200)
        self._token_expiry = time.monotonic() + max(60.0, expire - 120.0)
        return token

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, *, params=None, json_body=None,
                 auth: bool = True, retries: int = 6) -> Dict[str, Any]:
        url = path if path.startswith("http") else self.base + path
        attempt = 0
        while True:
            attempt += 1
            self.limiter.wait()
            headers: Dict[str, str] = {}
            if auth:
                headers["Authorization"] = f"Bearer {self.tenant_access_token()}"
            resp = self.session.request(
                method, url, params=params, json=json_body,
                headers=headers, timeout=self.s.http_timeout)

            if resp.status_code < 400:
                try:
                    data = resp.json() if resp.content else {}
                except ValueError:
                    data = {}
                code = data.get("code", 0)
                if code == 0:
                    return data
                if code in _TOKEN_ERROR_CODES and auth and attempt < retries:
                    self.log.warning("Feishu token error code=%s — refreshing",
                                     code)
                    self._token = ""
                    self._token_expiry = 0.0
                    continue
                raise FeishuApiError(
                    f"Feishu API code={code} on {method} {path}: "
                    f"{str(data.get('msg'))[:200]}")

            if resp.status_code in (401, 429, 500, 502, 503, 504) \
                    and attempt < retries:
                if resp.status_code == 401 and auth:
                    self._token = ""
                    self._token_expiry = 0.0
                retry_after = (resp.headers.get("Retry-After") or "").strip()
                delay = float(retry_after) if retry_after.isdigit() \
                    else backoff_delay(attempt)
                self.log.warning("HTTP %s on %s %s — retry #%d in %.1fs",
                                 resp.status_code, method, path, attempt, delay)
                time.sleep(delay)
                continue

            raise FeishuApiError(
                f"Feishu API {resp.status_code} on {method} {path}: "
                f"{resp.text[:300]}")

    # ------------------------------------------------------------------ #
    # docx primitives
    # ------------------------------------------------------------------ #
    def create_document(self, title: str,
                        folder_token: Optional[str] = None) -> str:
        body: Dict[str, Any] = {"title": title}
        if folder_token:
            body["folder_token"] = folder_token
        data = self._request("POST", "/open-apis/docx/v1/documents",
                             json_body=body)
        document = (data.get("data") or {}).get("document") or {}
        document_id = document.get("document_id") or ""
        if not document_id:
            raise FeishuApiError(
                f"document_id missing in create response: {str(data)[:200]}")
        return document_id

    def create_descendants(self, document_id: str, block_id: str,
                           children_id: List[str],
                           descendants: List[Dict[str, Any]]) -> Dict[str, Any]:
        body = {"children_id": children_id, "descendants": descendants}
        return self._request(
            "POST",
            f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}"
            "/descendant",
            json_body=body)

    # ------------------------------------------------------------------ #
    # media
    # ------------------------------------------------------------------ #
    def upload_media(self, path: Path, *, parent_type: str,
                     parent_node: str) -> Optional[str]:
        """Upload a local file as Feishu media; return its file_token."""
        p = Path(path)
        if not p.exists():
            return None
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        url = self.base + "/open-apis/drive/v1/medias/upload_all"
        for attempt in range(1, 4):
            self.limiter.wait()
            try:
                with open(p, "rb") as fh:
                    resp = self.session.post(
                        url,
                        files={"file": (p.name, fh, ctype)},
                        data={
                            "file_name": p.name,
                            "parent_type": parent_type,
                            "parent_node": parent_node,
                            "size": str(size),
                            "extra": json.dumps({"file_name": p.name}),
                        },
                        headers={"Authorization":
                                 f"Bearer {self.tenant_access_token()}"},
                        timeout=max(self.s.http_timeout, 120),
                    )
            except Exception as exc:  # noqa: BLE001 - upload is best-effort
                self.log.warning("media upload error %s: %s", p.name, exc)
                time.sleep(backoff_delay(attempt))
                continue
            if resp.status_code < 400:
                try:
                    data = resp.json() if resp.content else {}
                except ValueError:
                    data = {}
                if data.get("code") == 0:
                    token = (data.get("data") or {}).get("file_token")
                    if token:
                        return token
                self.log.warning("media upload failed %s: %s",
                                 p.name, str(data)[:200])
                return None
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(backoff_delay(attempt))
                continue
            self.log.warning("media upload HTTP %s on %s: %s",
                             resp.status_code, p.name, resp.text[:200])
            return None
        return None


# --------------------------------------------------------------------------- #
# Block conversion (pure functions — the unit-test surface)
# --------------------------------------------------------------------------- #
class _IdAllocator:
    """Hands out the temporary block ids the descendant API expects."""

    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"b{self.n}"


def _text_elements(rts: List[RichText]) -> List[Dict[str, Any]]:
    elements: List[Dict[str, Any]] = []
    for rt in rts or []:
        style: Dict[str, Any] = {}
        if rt.bold:
            style["bold"] = True
        if rt.italic:
            style["italic"] = True
        if rt.strikethrough:
            style["strikethrough"] = True
        if rt.underline:
            style["underline"] = True
        if rt.code:
            style["inline_code"] = True
        if rt.link:
            style["link"] = {"url": rt.link}
        elements.append({"text_run": {"content": rt.text,
                                      "text_element_style": style}})
    return elements


def _text_block(bid: str, content: str, *, style: Optional[Dict] = None,
                inline_code: bool = False) -> Dict[str, Any]:
    element_style: Dict[str, Any] = dict(style or {})
    if inline_code:
        element_style["inline_code"] = True
    return {"block_id": bid, "block_type": T_TEXT,
            "text": {"elements": [{"text_run": {
                "content": content, "text_element_style": element_style}}]}}


def _link_block(bid: str, prefix: str, url: str) -> Dict[str, Any]:
    return _text_block(bid, f"{prefix} {url}",
                       style={"link": {"url": url}})


def convert_block(block: Block, alloc: _IdAllocator, *,
                  upload_image=None) -> List[Dict[str, Any]]:
    """Convert one IR block (and its children) into Feishu descendant blocks.

    Returns the block's own node first, then its subtree, so callers can
    take ``result[0]["block_id"]`` as the top-level id.
    """
    btype = block.type

    # containers: keep the content, drop the wrapper
    if btype in ("synced_block", "column_list", "column"):
        out: List[Dict[str, Any]] = []
        for child in block.children:
            out.extend(convert_block(child, alloc, upload_image=upload_image))
        return out

    if btype in _SKIP_TYPES:
        return []

    if btype == "table":
        return _convert_table(block, alloc)

    if btype == "image":
        token = None
        local = (block.asset or {}).get("local_path")
        if local and upload_image is not None:
            token = upload_image(Path(local))
        if token:
            return [{"block_id": alloc.next(), "block_type": T_IMAGE,
                     "image": {"token": token}}]
        url = (block.asset or {}).get("url") or block.url or ""
        if url:
            return [_link_block(alloc.next(), "🖼", url)]
        return []

    if btype == "bookmark":
        url = block.url or ""
        return [_link_block(alloc.next(), "🔗", url)] if url else []

    if btype == "equation":
        expr = block.plain_text()
        return [_text_block(alloc.next(), expr, inline_code=True)] if expr \
            else []

    if btype == "divider":
        return [{"block_id": alloc.next(), "block_type": T_DIVIDER,
                 "divider": {}}]

    ftype = _IR_TO_FEISHU.get(btype)
    if ftype is None:
        # unknown type — degrade to a plain text block with its content
        text = block.plain_text()
        return [_text_block(alloc.next(), text)] if text else []

    payload: Dict[str, Any] = {"elements": _text_elements(block.text)}
    if not payload["elements"]:
        return []  # an empty text block carries nothing
    if ftype == T_TODO:
        payload["done"] = bool(block.checked)
    elif ftype == T_CODE:
        payload["language"] = _CODE_LANG.get((block.language or "").lower(), 1)

    node: Dict[str, Any] = {"block_id": alloc.next(),
                            "block_type": ftype,
                            _BODY_KEY[ftype]: payload}
    child_ids: List[str] = []
    subtree: List[Dict[str, Any]] = []
    for child in block.children:
        produced = convert_block(child, alloc, upload_image=upload_image)
        if produced:
            child_ids.append(produced[0]["block_id"])
            subtree.extend(produced)
    if child_ids:
        node["children"] = child_ids
    return [node] + subtree


def _convert_table(block: Block, alloc: _IdAllocator) -> List[Dict[str, Any]]:
    rows = [r for r in block.children if r.type == "table_row"] or \
           ([block] if block.cells else [])
    if not rows or not rows[0].cells:
        return []
    n_cols = max(len(r.cells) for r in rows)
    n_rows = len(rows)

    if n_cols > MAX_TABLE_COLUMNS or n_rows * n_cols > MAX_TABLE_CELLS:
        # too wide for a Feishu table — one monospaced line per row
        out: List[Dict[str, Any]] = []
        for r in rows:
            line = " | ".join("".join(rt.text for rt in cell)
                              for cell in r.cells)
            out.append(_text_block(alloc.next(), line, inline_code=True))
        return out

    cell_nodes: List[Dict[str, Any]] = []
    cell_ids: List[str] = []
    for r in rows:
        for ci in range(n_cols):
            cell = r.cells[ci] if ci < len(r.cells) else []
            cell_bid = alloc.next()
            text_bid = alloc.next()
            elements = _text_elements(cell) or [
                {"text_run": {"content": " ", "text_element_style": {}}}]
            cell_nodes.append({"block_id": cell_bid, "block_type": T_TABLE_CELL,
                               "table_cell": {}, "children": [text_bid]})
            cell_nodes.append({"block_id": text_bid, "block_type": T_TEXT,
                               "text": {"elements": elements}})
            cell_ids.append(cell_bid)

    table_bid = alloc.next()
    table_node = {"block_id": table_bid, "block_type": T_TABLE,
                  "table": {"property": {"row_size": n_rows,
                                         "column_size": n_cols}},
                  "children": cell_ids}
    return [table_node] + cell_nodes


def _cell_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "✓" if value else "—"
    return str(value)


def database_blocks(db: Dict[str, Any],
                    alloc: _IdAllocator) -> List[Dict[str, Any]]:
    """Render an exported inline database as a Feishu table block."""
    schema = db.get("schema") or {}
    rows = db.get("rows") or []
    if not rows:
        return []
    headers = list(schema.keys()) or ["Name"]
    header_row = Block(type="table_row",
                       cells=[[RichText(text=h)] for h in headers])
    body_rows = [Block(
        type="table_row",
        cells=[[RichText(text=_cell_text(row.get(h, "")))] for h in headers])
        for row in rows[:MAX_DB_ROWS]]
    return _convert_table(
        Block(type="table", children=[header_row] + body_rows), alloc)


def breadcrumb_block(page: PageNode, source_url: str,
                     bid: str = "breadcrumb") -> Dict[str, Any]:
    """Provenance callout prepended to every copied document."""
    path = " / ".join(page.path or [page.title])
    content = (f"Copied by notion-alchemist\n"
               f"Source: {source_url or '(unknown)'}\n"
               f"Path: {path}\n"
               f"Sub-pages are separate documents in the same folder.")
    return {"block_id": bid, "block_type": T_CALLOUT,
            "callout": {"elements": [
                {"text_run": {"content": content,
                              "text_element_style": {}}}]}}


def convert_blocks(blocks: List[Block], *, upload_image=None
                   ) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Convert top-level IR blocks -> (children_id, descendants)."""
    alloc = _IdAllocator()
    children_id: List[str] = []
    descendants: List[Dict[str, Any]] = []
    for block in blocks:
        produced = convert_block(block, alloc, upload_image=upload_image)
        if produced:
            children_id.append(produced[0]["block_id"])
            descendants.extend(produced)
    return children_id, descendants


def chunk_plan(children_id: List[str], descendants: List[Dict[str, Any]],
               limit: int = MAX_BLOCKS_PER_REQUEST
               ) -> List[Tuple[List[str], List[Dict[str, Any]]]]:
    """Split into per-request batches of at most ``limit`` blocks.

    A top-level block always travels with its whole subtree; a subtree
    larger than ``limit`` still goes out alone (the IR is pathological at
    that point — Feishu's own cap is 200).
    """
    by_id = {b["block_id"]: b for b in descendants}

    def subtree(bid: str) -> List[Dict[str, Any]]:
        node = by_id[bid]
        out = [node]
        for child in node.get("children", []):
            out.extend(subtree(child))
        return out

    batches: List[Tuple[List[str], List[Dict[str, Any]]]] = []
    cur_ids: List[str] = []
    cur_blocks: List[Dict[str, Any]] = []
    for cid in children_id:
        nodes = subtree(cid)
        if cur_ids and len(cur_blocks) + len(nodes) > limit:
            batches.append((cur_ids, cur_blocks))
            cur_ids, cur_blocks = [], []
        cur_ids.append(cid)
        cur_blocks.extend(nodes)
    if cur_ids:
        batches.append((cur_ids, cur_blocks))
    return batches


def document_url(document_id: str, base: str = FEISHU_BASE) -> str:
    host = "www.feishu.cn" if "feishu" in base else "www.larksuite.com"
    return f"https://{host}/docx/{document_id}"


# --------------------------------------------------------------------------- #
# Publisher
# --------------------------------------------------------------------------- #
class FeishuPublisher:
    def __init__(self, settings: Settings, *, dry_run: bool = False,
                 upload_files: bool = True, session=None):
        from .publish import StateStore

        self.s = settings
        self.dry_run = dry_run
        self.upload_files = upload_files
        self.log = get_logger()
        self.report = FeishuPublishReport()
        self.client: Optional[FeishuClient] = None
        if not dry_run:
            self.client = FeishuClient(settings, session=session)
        self.state = StateStore(Path(settings.state_dir) / STATE_FILENAME)
        self._current_document_id = ""
        self._uploaded: Dict[Tuple[str, str], Optional[str]] = {}

    # ------------------------------------------------------------------ #
    def _upload_image(self, local_path: Path) -> Optional[str]:
        if not self.upload_files or self.client is None \
                or not self._current_document_id:
            return None
        key = (self._current_document_id, str(local_path))
        if key not in self._uploaded:
            token = self.client.upload_media(
                local_path, parent_type="docx_image",
                parent_node=self._current_document_id)
            self._uploaded[key] = token
            if token:
                self.report.images_uploaded += 1
            else:
                self.report.skipped.append(f"image upload failed: {local_path}")
        return self._uploaded[key]

    # ------------------------------------------------------------------ #
    def publish(self, doc: Document,
                folder_token: Optional[str] = None) -> FeishuPublishReport:
        self.report.documents_total = sum(1 for _ in doc.iter_pages())
        for page, _depth in doc.iter_pages():
            try:
                self._publish_page(page, doc, folder_token)
            except FeishuApiError as exc:
                self.report.errors.append(f"{page.title}: {exc}")
                self.log.error("page %s failed: %s", page.title, exc)
            except Exception as exc:  # noqa: BLE001 - keep going, report at end
                self.report.errors.append(
                    f"{page.title}: {type(exc).__name__}: {exc}")
                self.log.error("page %s failed: %s", page.title, exc)
        self.report.finished_at = now_iso()
        return self.report

    def _publish_page(self, page: PageNode, doc: Document,
                      folder_token: Optional[str]) -> None:
        # resume: a fully written document is reused as-is; a document that
        # was created but never filled is re-filled in place.
        # (StateStore keeps the generic key `page_id` — here it holds the
        # Feishu document_id.)
        existing = self.state.page_entry(page.source_id)
        document_id = ""
        refill = False
        if existing and existing.get("page_id"):
            document_id = existing["page_id"]
            if (existing.get("units") or 0) > 0:
                self.report.documents_reused += 1
                self.report.documents.append({
                    "title": page.title,
                    "document_id": document_id,
                    "url": document_url(document_id, self.s.feishu_base),
                    "reused": True,
                })
                return
            refill = True
            self.log.info("re-filling partially written document %s",
                          document_id)

        if not document_id:
            if self.dry_run:
                document_id = f"dry-run-{slugify(page.title)}"
            else:
                assert self.client is not None
                document_id = self.client.create_document(
                    page.title, folder_token=folder_token)

        self._current_document_id = document_id

        # breadcrumb (raw Feishu payload) + converted page blocks + database
        children_id, descendants = convert_blocks(
            page.blocks, upload_image=self._upload_image)
        if page.database:
            alloc = _IdAllocator()
            alloc.n = len(descendants)  # keep temp ids unique across merge
            db_blocks = database_blocks(page.database, alloc)
            if db_blocks:
                children_id.append(db_blocks[0]["block_id"])
                descendants.extend(db_blocks)
            if (page.database.get("row_count") or 0) > MAX_DB_ROWS:
                self.report.skipped.append(
                    f"{page.title}: database truncated to "
                    f"{MAX_DB_ROWS} rows")

        breadcrumb = breadcrumb_block(page, doc.source_url)
        children_id.insert(0, breadcrumb["block_id"])
        descendants.insert(0, breadcrumb)

        self.report.blocks_total += len(descendants)
        if not self.dry_run:
            assert self.client is not None
            for batch_ids, batch_blocks in chunk_plan(children_id,
                                                      descendants):
                self.client.create_descendants(
                    document_id, document_id, batch_ids, batch_blocks)

        self.report.documents.append({
            "title": page.title,
            "document_id": document_id,
            "url": document_url(document_id, self.s.feishu_base),
            "reused": False,
            "blocks": len(descendants),
        })
        if not self.dry_run:
            if refill:
                self.report.documents_refilled += 1
            else:
                self.report.documents_created += 1
            self.state.set_page(page.source_id, page_id=document_id,
                                units=len(children_id))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def publish_to_feishu(doc: Document, settings: Settings, *,
                      folder_token: Optional[str] = None,
                      dry_run: bool = False,
                      upload_files: bool = True) -> FeishuPublishReport:
    """Write a (transformed) IR document into Feishu Docs."""
    folder = (folder_token or settings.feishu_folder or "").strip()
    if not dry_run:
        problems = settings.problems_feishu()
        if problems:
            raise ValueError("; ".join(problems))
    publisher = FeishuPublisher(settings, dry_run=dry_run,
                                upload_files=upload_files)
    return publisher.publish(doc, folder_token=folder or None)
