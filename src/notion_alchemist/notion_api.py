"""Official Notion API engine — read a page tree into the IR.

Design notes
------------
* `Notion-Version: 2022-06-28` is pinned deliberately: it is the most widely
  compatible version and everything we need (pages, blocks, databases) is
  available there.
* Rate limiting: 3 req/s is the cross-plan safe default; we throttle with a
  minimum interval and honour `Retry-After` on 429.
* 503 handling: Notion documents `retry_guidance: do_not_retry` for writes that
  actually landed — we surface those to the caller instead of blindly retrying.
* Assets are downloaded at extraction time because Notion file URLs are signed
  and expire (typically within an hour).
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import Settings
from .models import Block, Document, PageNode, RichText
from .util import (
    RateLimiter,
    backoff_delay,
    get_logger,
    now_iso,
    safe_filename,
    sha1_bytes,
)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_DEPTH = 12  # safety valve against pathological trees


class NotionApiError(RuntimeError):
    """Raised for non-retryable Notion API failures."""


class NotionClient:
    def __init__(self, settings: Settings, *, download_assets: bool = False,
                 asset_dir: Optional[Path] = None, session=None):
        import requests  # local import: keeps `--help` fast

        self.s = settings
        self._requests = requests
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
        self.limiter = RateLimiter(settings.max_rps)
        self.log = get_logger()
        self.download_assets = download_assets
        self.asset_dir = Path(asset_dir) if asset_dir else None
        if self.download_assets and self.asset_dir:
            self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"api_calls": 0, "assets_downloaded": 0, "pages": 0, "blocks": 0}

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, *, params=None, json_body=None,
                 retries: int = 6) -> Dict[str, Any]:
        url = path if path.startswith("http") else API_BASE + path
        attempt = 0
        while True:
            attempt += 1
            self.limiter.wait()
            self.stats["api_calls"] += 1
            resp = self.session.request(
                method, url, params=params, json=json_body, timeout=self.s.http_timeout
            )
            if resp.status_code < 400:
                return resp.json() if resp.content else {}

            if resp.status_code == 503:
                # A 503 can mean "succeeded but response lost" — Notion says so
                # explicitly via retry_guidance. Never replay those.
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                if str(body.get("retry_guidance", "")).lower() == "do_not_retry":
                    self.log.warning("503 do_not_retry on %s %s — treating as applied",
                                     method, path)
                    return body

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = (resp.headers.get("Retry-After") or "").strip()
                delay = float(retry_after) if retry_after.isdigit() else backoff_delay(attempt)
                self.log.warning("HTTP %s on %s %s — retry #%d in %.1fs",
                                 resp.status_code, method, path, attempt, delay)
                time.sleep(delay)
                continue

            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:500]}
            raise NotionApiError(
                f"Notion API {resp.status_code} on {method} {path}: {str(body)[:500]}"
            )

    # ------------------------------------------------------------------ #
    # Read primitives
    # ------------------------------------------------------------------ #
    def get_page(self, page_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/pages/{page_id}")

    def get_block(self, block_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/blocks/{block_id}")

    def list_block_children(self, block_id: str, start_cursor: Optional[str] = None):
        params = {"page_size": 100}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._request("GET", f"/blocks/{block_id}/children", params=params)

    def iter_block_children(self, block_id: str) -> Iterable[Dict[str, Any]]:
        cursor = None
        while True:
            data = self.list_block_children(block_id, cursor)
            for item in data.get("results", []):
                yield item
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")

    def retrieve_database(self, database_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/databases/{database_id}")

    def query_database(self, database_id: str, start_cursor: Optional[str] = None):
        body: Dict[str, Any] = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._request("POST", f"/databases/{database_id}/query", json_body=body)

    # ------------------------------------------------------------------ #
    # Converters
    # ------------------------------------------------------------------ #
    @staticmethod
    def _file_url(payload: Dict[str, Any]) -> Optional[str]:
        f = payload.get("file") or {}
        e = payload.get("external") or {}
        return f.get("url") or e.get("url") or payload.get("url")

    def rich_text_from_notion(self, items) -> List[RichText]:
        out: List[RichText] = []
        for it in items or []:
            it = it or {}
            t = it.get("type", "text")
            if t == "equation":
                out.append(RichText(text=(it.get("equation") or {}).get("expression", ""),
                                    kind="equation", code=True))
                continue
            if t == "mention":
                mention = it.get("mention") or {}
                mtype = mention.get("type", "unknown")
                label = it.get("plain_text") or f"@{mtype}"
                out.append(RichText(text=label, kind="mention", color="default"))
                continue
            payload = it.get("text") or {}
            ann = it.get("annotations") or {}
            link = it.get("href") or (payload.get("link") or {}).get("url")
            out.append(RichText(
                text=payload.get("content", it.get("plain_text", "")),
                bold=bool(ann.get("bold")),
                italic=bool(ann.get("italic")),
                strikethrough=bool(ann.get("strikethrough")),
                underline=bool(ann.get("underline")),
                code=bool(ann.get("code")),
                color=ann.get("color", "default") or "default",
                link=link,
            ))
        return out

    def _download_asset(self, url: str, kind: str, hint: str = "") -> Optional[Dict[str, Any]]:
        if not self.download_assets or not self.asset_dir:
            return {"name": hint or "file", "url": url, "kind": kind}
        try:
            resp = self._requests.get(url, timeout=self.s.http_timeout)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - never fail extraction on assets
            self.log.warning("asset download failed (%s): %s", url[:80], exc)
            return {"name": hint or "file", "url": url, "kind": kind}
        data = resp.content
        digest = sha1_bytes(data)
        ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
        ext = mimetypes.guess_extension(ctype) or ""
        if not ext and "." in url.split("?")[0].rsplit("/", 1)[-1]:
            ext = "." + url.split("?")[0].rsplit(".", 1)[-1][:8]
        name = f"{digest[:16]}{ext}"
        path = self.asset_dir / name
        if not path.exists():
            path.write_bytes(data)
        self.stats["assets_downloaded"] += 1
        orig = safe_filename(hint or Path(url.split("?")[0]).name or name)
        return {"name": orig, "url": url, "kind": kind,
                "local_path": str(path), "sha1": digest}

    def block_from_notion(self, b: Dict[str, Any], _depth: int = 0) -> Block:
        btype = b.get("type", "paragraph")
        payload = b.get(btype) or {}
        blk = Block(type=btype, raw=b)
        if btype == "table_row":
            blk.cells = [self.rich_text_from_notion(cell)
                         for cell in payload.get("cells", [])]
            self.stats["blocks"] += 1
            return blk
        if btype == "link_to_page":
            ref = payload.get("page_id") or payload.get("database_id") or ""
            blk.text = [RichText(text=ref, kind="mention")] if ref else []
            self.stats["blocks"] += 1
            return blk
        blk.text = self.rich_text_from_notion(payload.get("rich_text"))
        if "caption" in payload:
            blk.caption = self.rich_text_from_notion(payload.get("caption"))
        if "checked" in payload:
            blk.checked = bool(payload.get("checked"))
        if "language" in payload:
            blk.language = payload.get("language")

        url = self._file_url(payload)
        if btype == "image":
            blk.url = url
            if url:
                blk.asset = self._download_asset(url, "image", "image")
        elif btype in ("file", "pdf", "video"):
            blk.url = url
            if url:
                blk.asset = self._download_asset(url, "file", payload.get("name") or "file")
        elif btype in ("bookmark", "embed"):
            blk.url = url

        if b.get("has_children") and btype not in ("child_page", "child_database") \
                and _depth < MAX_DEPTH:
            blk.children = [self.block_from_notion(c, _depth + 1)
                            for c in self.iter_block_children(b["id"])]
        self.stats["blocks"] += 1
        return blk

    @staticmethod
    def _page_title(page: Dict[str, Any]) -> str:
        for prop in (page.get("properties") or {}).values():
            if prop.get("type") == "title":
                return "".join(rt.get("plain_text", "")
                               for rt in prop.get("title") or []) or "Untitled"
        return "Untitled"

    @staticmethod
    def _icon(page: Dict[str, Any]) -> Optional[str]:
        icon = page.get("icon") or {}
        if icon.get("type") == "emoji":
            return icon.get("emoji")
        if icon.get("type") == "external":
            return (icon.get("external") or {}).get("url")
        if icon.get("type") == "file":
            return (icon.get("file") or {}).get("url")
        return None

    @staticmethod
    def _cover(page: Dict[str, Any]) -> Optional[str]:
        cover = page.get("cover") or {}
        if cover.get("type") == "external":
            return (cover.get("external") or {}).get("url")
        if cover.get("type") == "file":
            return (cover.get("file") or {}).get("url")
        return None

    @staticmethod
    def flatten_properties(props: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Notion page properties into plain JSON values."""
        out: Dict[str, Any] = {}
        for name, spec in (props or {}).items():
            ptype = spec.get("type")
            try:
                if ptype == "title":
                    out[name] = "".join(rt.get("plain_text", "")
                                        for rt in spec.get("title") or [])
                elif ptype == "rich_text":
                    out[name] = "".join(rt.get("plain_text", "")
                                        for rt in spec.get("rich_text") or [])
                elif ptype == "number":
                    out[name] = spec.get("number")
                elif ptype == "select":
                    sel = spec.get("select")
                    out[name] = sel.get("name") if sel else None
                elif ptype == "multi_select":
                    out[name] = [s.get("name") for s in spec.get("multi_select") or []]
                elif ptype == "date":
                    date = spec.get("date") or {}
                    out[name] = date.get("start")
                elif ptype in ("checkbox",):
                    out[name] = bool(spec.get("checkbox"))
                elif ptype in ("url", "email", "phone_number"):
                    out[name] = spec.get(ptype)
                elif ptype == "people":
                    out[name] = [p.get("name") or p.get("id") for p in spec.get("people") or []]
                elif ptype == "created_time":
                    out[name] = spec.get("created_time")
                elif ptype == "last_edited_time":
                    out[name] = spec.get("last_edited_time")
                else:
                    out[name] = None
            except Exception:  # noqa: BLE001 - unknown shapes degrade to None
                out[name] = None
        return out

    # ------------------------------------------------------------------ #
    # Tree reading
    # ------------------------------------------------------------------ #
    def read_database(self, database_id: str) -> Dict[str, Any]:
        schema_raw = (self.retrieve_database(database_id).get("properties") or {})
        schema = {name: spec.get("type") for name, spec in schema_raw.items()}
        rows: List[Dict[str, Any]] = []
        cursor = None
        while True:
            data = self.query_database(database_id, cursor)
            for page in data.get("results", []):
                rows.append(self.flatten_properties(page.get("properties") or {}))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return {"schema": schema, "raw_schema": schema_raw, "rows": rows,
                "row_count": len(rows)}

    def page_to_node(self, page_id: str, path: Optional[List[str]] = None,
                     seen: Optional[set] = None, depth: int = 0) -> PageNode:
        path = path or []
        seen = seen if seen is not None else set()
        page = self.get_page(page_id)
        node = PageNode(
            source_id=page_id,
            title=self._page_title(page),
            icon=self._icon(page),
            cover=self._cover(page),
            properties=self.flatten_properties(page.get("properties") or {}),
            path=list(path),
        )
        node.ensure_slug()
        self.stats["pages"] += 1
        self.log.info("read page %s%s", node.title, f"  (depth {depth})" if depth else "")

        child_pages: List[Dict[str, Any]] = []
        child_databases: List[Dict[str, Any]] = []
        for raw in self.iter_block_children(page_id):
            if raw.get("type") == "child_page":
                child_pages.append(raw)
            elif raw.get("type") == "child_database":
                child_databases.append(raw)
            else:
                node.blocks.append(self.block_from_notion(raw))

        for raw in child_pages:
            cid = raw["id"]
            if cid in seen or depth >= MAX_DEPTH:
                node.blocks.append(Block(type="child_page",
                                         text=[RichText(text=raw.get("child_page", {})
                                                        .get("title", "Untitled"))],
                                         raw=raw))
                continue
            seen.add(cid)
            node.children.append(
                self.page_to_node(cid, path=path + [node.title], seen=seen, depth=depth + 1)
            )

        for raw in child_databases:
            db_id = raw["id"]
            title = (raw.get("child_database") or {}).get("title", "Database")
            try:
                node.database = self.read_database(db_id)
                node.notes.append(f"database '{title}': {node.database['row_count']} rows")
            except NotionApiError as exc:
                node.notes.append(f"database '{title}' unreadable: {exc}")
            node.blocks.append(Block(type="child_database",
                                     text=[RichText(text=title)], raw=raw))
        return node


def extract_via_api(url: str, settings: Settings, *, download_assets: bool = True,
                    asset_dir: Optional[Path] = None) -> Document:
    """Extract the page tree rooted at `url` into a `Document`."""
    from .util import extract_notion_id

    page_id = extract_notion_id(url)
    client = NotionClient(settings, download_assets=download_assets, asset_dir=asset_dir)
    root = client.page_to_node(page_id)
    doc = Document(source_url=url, engine="api", extracted_at=now_iso(), pages=[root])
    doc.stats = dict(client.stats)
    doc.stats["blocks_total"] = doc.count_blocks()
    return doc
