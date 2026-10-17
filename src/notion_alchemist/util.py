"""Small shared utilities: id parsing, slugs, rate limiting, logging, hashing."""
from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

LOGGER_NAME = "notion-alchemist"

_HEX32 = re.compile(r"[0-9a-f]{32}", re.I)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
_BARE32 = re.compile(r"^[0-9a-f]{32}$", re.I)
_NON_SLUG = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


# --------------------------------------------------------------------------- #
# time / logging
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


# --------------------------------------------------------------------------- #
# Notion id handling
# --------------------------------------------------------------------------- #
def format_uuid(hex32: str) -> str:
    h = hex32.lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def extract_notion_id(value: str) -> str:
    """Accept a page URL, a 32-hex id or a dashed UUID; return a dashed UUID.

    Handles notion.so / notion.site / custom-domain URLs, with or without
    query strings (``?pvs=…``) and trailing slashes.
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("empty Notion id / url")
    if _UUID_RE.match(v):
        return v.lower()
    if _BARE32.match(v):
        return format_uuid(v)

    parsed = urlparse(v if "://" in v else "https://" + v)
    tail = parsed.path.rstrip("/").split("/")[-1] if parsed.path else ""
    m = re.search(r"[0-9a-f]{32}$", tail, re.I)
    if m:
        return format_uuid(m.group(0))
    m = _HEX32.search(v)
    if m:
        return format_uuid(m.group(0))
    raise ValueError(
        f"could not extract a Notion page id from {value!r}. "
        "Expected a page URL, a 32-char hex id, or a dashed UUID."
    )


# --------------------------------------------------------------------------- #
# slugs & filenames
# --------------------------------------------------------------------------- #
def slugify(text: str, max_len: int = 60) -> str:
    s = (text or "").strip().lower()
    s = _NON_SLUG.sub("-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def safe_filename(name: str, default: str = "file") -> str:
    s = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", (name or "").strip())
    s = s.strip(" .")
    return s or default


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# rate limiting & backoff
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Simple minimum-interval limiter (single-threaded CLI usage)."""

    def __init__(self, rps: float = 2.5):
        self.min_interval = 1.0 / float(rps) if rps and rps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        delta = self.min_interval - (now - self._last)
        if delta > 0:
            time.sleep(delta)
        self._last = time.monotonic()


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1))) + random.uniform(0, 0.25)


# --------------------------------------------------------------------------- #
# dotenv (tiny, dependency-free)
# --------------------------------------------------------------------------- #
def load_dotenv(path: str | os.PathLike = ".env", override: bool = False) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = val
    return True
