"""EXPERIMENTAL — unofficial export engine (fallback for view-only pages).

When a page can be *viewed* but not shared with an integration (guest access
to a paid template library, for example), the official API cannot read it.
Notion's own export feature can, though — and this module drives it:

    POST /api/v3/enqueueTask  {eventName: "exportBlock", ...}
    POST /api/v3/getTasks     (poll until state == "success")
    GET  <exportURL>          (signed ZIP: Markdown + CSV + assets)

It uses the ``token_v2`` session cookie from a logged-in browser, expires with
it (~1 year), and is a private endpoint: **it may break without notice**.
That is why it is a fallback, clearly separated from ``notion_api.py``, and
gated behind ``--experimental``.

Alternatively the engine can ingest a ZIP the user exported by hand
(``... → Export → Markdown & CSV``), which needs no cookie at all.
"""
from __future__ import annotations

import csv
import io
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings
from .models import Block, Document, PageNode, RichText
from .util import get_logger, now_iso, safe_filename, slugify

API_BASE = "https://www.notion.so/api/v3"
EXPORT_PAGE = "https://www.notion.so/{slug}"

_SPACE_ID_RE = re.compile(
    r"spaceId[\"=:\s]{1,4}\"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})", re.I)
_HASH_SUFFIX_RE = re.compile(r"\s+[0-9a-f]{8,}$", re.I)


class UnofficialExportError(RuntimeError):
    """Raised when the experimental export pipeline fails."""


# --------------------------------------------------------------------------- #
# Export orchestration
# --------------------------------------------------------------------------- #
class NotionUnofficialExporter:
    def __init__(self, settings: Settings, *, poll_interval: float = 2.0,
                 timeout: float = 900.0):
        import requests  # local import keeps --help fast

        self.s = settings
        self._requests = requests
        self.session = requests.Session()
        cookie = f"token_v2={settings.notion_token_v2}"
        if settings.file_token:
            cookie += f"; file_token={settings.file_token}"
        self.session.headers.update({
            "Cookie": cookie,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.log = get_logger()

    # ------------------------------------------------------------------ #
    def _post(self, endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.post(f"{API_BASE}/{endpoint}", json=body,
                                 timeout=self.s.http_timeout)
        if resp.status_code >= 400:
            raise UnofficialExportError(
                f"{endpoint} -> HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise UnofficialExportError(f"{endpoint} returned non-JSON: {exc}")

    def get_space_id(self, page_url: str) -> str:
        """Discover the workspace id a page lives in by parsing its HTML."""
        url = page_url if "://" in page_url else f"https://{page_url}"
        resp = self.session.get(url, timeout=self.s.http_timeout,
                                headers={"Accept": "text/html"})
        if resp.status_code >= 400:
            raise UnofficialExportError(
                f"cannot open {url} (HTTP {resp.status_code}) — is the page "
                "shared with your account, and is NOTION_TOKEN_V2 still valid?")
        match = _SPACE_ID_RE.search(resp.text)
        if not match:
            raise UnofficialExportError(
                "could not find a spaceId in the page HTML; open the page in "
                "your browser and copy the spaceId from the export request "
                "payload in DevTools (see docs/notion-token-setup.md)")
        return match.group(1)

    def enqueue_export(self, block_id: str, space_id: str,
                       recursive: bool = True) -> str:
        data = self._post("enqueueTask", {"task": {
            "eventName": "exportBlock",
            "request": {
                "block": {"id": block_id, "spaceId": space_id},
                "exportOptions": {"exportType": "markdown",
                                  "locale": "en",
                                  "timeZone": "UTC"},
                "recursive": bool(recursive),
            },
        }})
        task_id = data.get("taskId")
        if not task_id:
            raise UnofficialExportError(f"enqueueTask gave no taskId: {data}")
        self.log.info("export task %s enqueued (recursive=%s)", task_id, recursive)
        return task_id

    def poll_export(self, task_id: str) -> str:
        """Poll getTasks until the export finishes; return the ZIP url."""
        deadline = time.monotonic() + self.timeout
        last = ""
        while time.monotonic() < deadline:
            data = self._post("getTasks", {"taskIds": [task_id]})
            for task in data.get("results", []):
                if task.get("id") != task_id:
                    continue
                state = task.get("state")
                status = task.get("status") or {}
                pages = status.get("pagesExported")
                if pages is not None and str(pages) != last:
                    self.log.info("exporting… %s pages", pages)
                    last = str(pages)
                if state == "success":
                    url = status.get("exportURL")
                    if not url:
                        raise UnofficialExportError("task succeeded without exportURL")
                    return url
                if state in ("failure", "failed"):
                    raise UnofficialExportError(
                        f"export task failed: {str(task)[:300]}")
            time.sleep(self.poll_interval)
        raise UnofficialExportError(f"export task {task_id} timed out")

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True,
                              timeout=max(self.s.http_timeout, 120)) as resp:
            if resp.status_code >= 400:
                raise UnofficialExportError(
                    f"download failed (HTTP {resp.status_code})")
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
        self.log.info("downloaded %s (%.1f KB)", dest.name,
                      dest.stat().st_size / 1024)
        return dest

    def export(self, page_url: str, *, recursive: bool = True,
               workdir: Optional[Path] = None) -> Path:
        """Run the whole unofficial export; return the downloaded ZIP path."""
        from .util import extract_notion_id

        problems = self.s.problems_unofficial()
        if problems:
            raise UnofficialExportError("; ".join(problems))
        block_id = extract_notion_id(page_url)
        space_id = self.get_space_id(page_url)
        task_id = self.enqueue_export(block_id, space_id, recursive=recursive)
        url = self.poll_export(task_id)
        workdir = Path(workdir or tempfile.mkdtemp(prefix="na-export-"))
        return self.download(url, workdir / f"export-{block_id[:8]}.zip")


# --------------------------------------------------------------------------- #
# Inline markdown -> rich text
# --------------------------------------------------------------------------- #
_INLINE_RE = re.compile(
    r"(\*\*[^*]+?\*\*|\*[^*\n]+?\*|__[^_]+?__|_[^_\n]+?_|`[^`\n]+?`|"
    r"~~[^~]+?~~|\[[^\]]*?\]\([^)\s]+?\))")


def _inline(text: str) -> List[RichText]:
    """Very small inline-markdown parser (bold/italic/code/strike/link)."""
    out: List[RichText] = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            out.append(RichText(text=text[pos:match.start()]))
        token = match.group(0)
        if token.startswith("**") or token.startswith("__"):
            out.append(RichText(text=token[2:-2], bold=True))
        elif token.startswith("~~"):
            out.append(RichText(text=token[2:-2], strikethrough=True))
        elif token.startswith("`"):
            out.append(RichText(text=token[1:-1], code=True))
        elif token.startswith("["):
            m = re.match(r"\[([^\]]*)\]\(([^)]+)\)", token)
            if m:
                out.append(RichText(text=m.group(1), link=m.group(2)))
            else:  # pragma: no cover - regex guarantees the shape
                out.append(RichText(text=token))
        else:
            out.append(RichText(text=token[1:-1], italic=True))
        pos = match.end()
    if pos < len(text):
        out.append(RichText(text=text[pos:]))
    return [rt for rt in out if rt.text or rt.kind == "equation"]


def _is_emoji(text: str) -> bool:
    return bool(text) and all(ord(ch) >= 0x2000 for ch in text[:2])


# --------------------------------------------------------------------------- #
# Block-level markdown -> IR
# --------------------------------------------------------------------------- #
def _is_block_start(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return bool(
        s.startswith(("#", ">", "```", "---", "***", "___", "|", "- [", "- ", "* "))
        or re.match(r"^\d+\.\s", s)
        or re.match(r"^!\[[^\]]*\]\([^)]+\)\s*$", s)
    )


def _resolve_asset(href: str, base_dir: Optional[Path]) -> Dict[str, Any]:
    name = href.split("/")[-1].split("?")[0]
    asset: Dict[str, Any] = {"name": safe_filename(name or "file"),
                             "kind": "image", "url": href}
    if base_dir and not href.lower().startswith(("http://", "https://")):
        candidate = (base_dir / href).resolve()
        if candidate.exists():
            asset["local_path"] = str(candidate)
    return asset


def parse_markdown(md: str, base_dir: Optional[Path] = None) -> List[Block]:
    """Parse one Notion-exported Markdown file into IR blocks.

    Deliberately tolerant: the export format is the fallback path, and losing
    a rare construct is preferable to failing the whole archive.
    """
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Block] = []
    list_stack: List[Block] = []
    i = 0

    def add_list(block: Block, level: int) -> None:
        while len(list_stack) > level:
            list_stack.pop()
        if level == 0 or not list_stack:
            blocks.append(block)
        else:
            list_stack[-1].children.append(block)
        list_stack.append(block)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            list_stack.clear()
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            language = stripped[3:].strip() or None
            i += 1
            buf: List[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block(type="code", text=[RichText(text="\n".join(buf))],
                                language=language))
            continue

        # divider
        if stripped in ("---", "***", "___"):
            blocks.append(Block(type="divider"))
            i += 1
            continue

        # heading
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            blocks.append(Block(type=f"heading_{len(m.group(1))}",
                                text=_inline(m.group(2))))
            i += 1
            continue

        # quote / callout (may span lines)
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            text = " ".join(x for x in buf if x)
            first = text.split(" ", 1)[0] if text else ""
            if _is_emoji(first) and len(text) > len(first):
                blocks.append(Block(type="callout",
                                    text=_inline(text[len(first):].strip())))
            else:
                blocks.append(Block(type="quote", text=_inline(text)))
            continue

        # standalone image
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if m:
            alt, href = m.group(1), m.group(2)
            blocks.append(Block(type="image", url=href,
                                asset=_resolve_asset(href, base_dir)))
            i += 1
            continue

        # table
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(
                r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", lines[i + 1]):
            rows: List[List[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{1,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                table = Block(type="table",
                              raw={"table": {"table_width": width}},
                              children=[Block(type="table_row",
                                              cells=[_inline(c) for c in row])
                                        for row in rows])
                blocks.append(table)
            continue

        # list items
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            indent, marker, content = m.group(1), m.group(2), m.group(3)
            level = len(indent.replace("\t", "  ")) // 2
            todo = re.match(r"^\[([ xX])\]\s+(.*)$", content)
            if todo:
                add_list(Block(type="to_do", text=_inline(todo.group(2)),
                               checked=todo.group(1).lower() == "x"), level)
            else:
                kind = ("numbered_list_item" if re.fullmatch(r"\d+[.)]", marker)
                        else "bulleted_list_item")
                add_list(Block(type=kind, text=_inline(content)), level)
            i += 1
            continue

        # paragraph (until a blank line or the next block starts)
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            buf.append(lines[i])
            i += 1
        text = "\n".join(buf).strip()
        list_stack.clear()
        link_only = re.fullmatch(r"\[([^\]]*)\]\(([^)]+)\)", text)
        if link_only and not link_only.group(2).lower().endswith(".md"):
            blocks.append(Block(type="bookmark", url=link_only.group(2)))
        elif text:
            blocks.append(Block(type="paragraph", text=_inline(text)))

    return blocks


# --------------------------------------------------------------------------- #
# Export ZIP -> IR document
# --------------------------------------------------------------------------- #
def _page_title_from_name(name: str) -> str:
    stem = name[:-3] if name.lower().endswith(".md") else name
    return _HASH_SUFFIX_RE.sub("", stem).strip() or "Untitled"


def _read_csv(text: str) -> Dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(text)))
    schema = {name: "rich_text" for name in (rows[0].keys() if rows else [])}
    return {"schema": schema, "raw_schema": {k: {"type": "rich_text"}
                                             for k in schema},
            "rows": rows, "row_count": len(rows)}


def parse_export_zip(zip_path: Path, *, extract_dir: Optional[Path] = None
                     ) -> Tuple[Document, Path]:
    """Unpack a Notion Markdown/CSV export ZIP and build the IR tree.

    Layout heuristics (Notion appends a short hash to every name):
      * ``<dir>/<page> <hash>.md`` is a page; its directory is the folder.
      * a page's parent is the ``.md`` file in the closest ancestor directory.
      * ``<dir>/<db> <hash>.csv`` becomes the database of the page owning
        that directory.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise UnofficialExportError(f"export zip not found: {zip_path}")
    target = Path(extract_dir) if extract_dir else Path(
        tempfile.mkdtemp(prefix="na-unzip-"))
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)

    md_files = sorted(p for p in target.rglob("*.md")
                      if not p.name.startswith(("~", ".")))
    csv_files = sorted(p for p in target.rglob("*.csv"))
    if not md_files:
        raise UnofficialExportError(
            f"no markdown files found in {zip_path.name} — was it exported as "
            "'Markdown & CSV'?")

    nodes: Dict[Path, PageNode] = {}
    for md in md_files:
        node = PageNode(source_id="", title=_page_title_from_name(md.name),
                        path=[], slug=slugify(_page_title_from_name(md.name)))
        node.blocks = parse_markdown(md.read_text(encoding="utf-8",
                                                  errors="replace"),
                                     base_dir=md.parent)
        # a leading H1 that repeats the file name is the exported title
        if node.blocks and node.blocks[0].type == "heading_1" \
                and node.blocks[0].plain_text().strip() == node.title:
            node.blocks.pop(0)
        nodes[md] = node

    roots: List[PageNode] = []
    for md, node in nodes.items():
        parent_node = None
        ancestor = md.parent.parent
        while ancestor >= target:
            candidate = nodes.get(ancestor / (ancestor.name + ".md"))
            if candidate is None:
                # the folder name may carry the same hash suffix as the md
                candidate = next((n for p, n in nodes.items()
                                  if p.parent == ancestor), None)
            if candidate is not None:
                parent_node = candidate
                break
            ancestor = ancestor.parent
        if parent_node is not None and parent_node is not node:
            parent_node.children.append(node)
            node.path = parent_node.path + [parent_node.title]
        else:
            roots.append(node)

    for csv_path in csv_files:
        owner = None
        folder = csv_path.parent
        for md, node in nodes.items():
            if md.parent == folder:
                owner = node
                break
        if owner is None:
            continue
        try:
            owner.database = _read_csv(csv_path.read_text(encoding="utf-8",
                                                          errors="replace"))
            owner.notes.append(f"csv '{_page_title_from_name(csv_path.name)}': "
                               f"{owner.database['row_count']} rows")
        except Exception as exc:  # noqa: BLE001 - a bad CSV must not kill the run
            owner.notes.append(f"csv '{csv_path.name}' unreadable: {exc}")

    doc = Document(source_url=str(zip_path), engine="export",
                   extracted_at=now_iso(), pages=roots)
    doc.stats = {"pages": len(nodes), "blocks": doc.count_blocks(),
                 "csv_files": len(csv_files)}
    return doc, target


def extract_via_export(url: str, settings: Settings, *, recursive: bool = True,
                       workdir: Optional[Path] = None,
                       zip_path: Optional[Path] = None) -> Document:
    """Extract via the experimental export engine (or a pre-made ZIP)."""
    if zip_path:
        doc, _ = parse_export_zip(Path(zip_path))
        doc.source_url = url
        return doc
    exporter = NotionUnofficialExporter(settings)
    downloaded = exporter.export(url, recursive=recursive, workdir=workdir)
    doc, _ = parse_export_zip(downloaded)
    doc.source_url = url
    return doc
