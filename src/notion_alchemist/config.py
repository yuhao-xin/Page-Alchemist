"""Configuration — environment variables plus an optional `.env` file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from .util import load_dotenv

ENV_FILE = ".env"


@dataclass
class Settings:
    notion_token: str = ""
    notion_token_v2: str = ""
    file_token: str = ""
    parent_page: str = ""
    icon_mode: str = "retune"          # keep | retune | none
    max_rps: float = 2.5
    http_timeout: float = 30.0
    log_level: str = "INFO"
    state_dir: str = "."               # where .na_state.json lives
    output_dir: str = "output"

    # -------------------------------------------------------------- #
    @classmethod
    def load(cls, env_file: str = ENV_FILE) -> "Settings":
        load_dotenv(env_file)
        return cls(
            notion_token=os.environ.get("NOTION_TOKEN", "").strip(),
            notion_token_v2=os.environ.get("NOTION_TOKEN_V2", "").strip(),
            file_token=os.environ.get("NOTION_FILE_TOKEN", "").strip(),
            parent_page=os.environ.get("NA_PARENT_PAGE", "").strip(),
            icon_mode=os.environ.get("NA_ICON_MODE", "retune").strip() or "retune",
            max_rps=float(os.environ.get("NA_MAX_RPS", "2.5") or 2.5),
            http_timeout=float(os.environ.get("NA_HTTP_TIMEOUT", "30") or 30),
            log_level=os.environ.get("NA_LOG_LEVEL", "INFO").strip() or "INFO",
            state_dir=os.environ.get("NA_STATE_DIR", ".").strip() or ".",
            output_dir=os.environ.get("NA_OUTPUT_DIR", "output").strip() or "output",
        )

    # -------------------------------------------------------------- #
    def problems(self, *, need_token: bool = False, need_parent: bool = False) -> List[str]:
        """Return a list of human-readable configuration problems."""
        issues: List[str] = []
        if need_token and not self.notion_token:
            issues.append(
                "NOTION_TOKEN is not set. Create an integration at "
                "https://www.notion.so/my-integrations and share the page with it "
                "(see docs/notion-token-setup.md)."
            )
        if need_parent and not self.parent_page:
            issues.append(
                "NA_PARENT_PAGE is not set. Provide the target parent page "
                "(--parent) in your own workspace."
            )
        if self.icon_mode not in ("keep", "retune", "none"):
            issues.append(f"NA_ICON_MODE must be keep|retune|none, got {self.icon_mode!r}")
        if self.max_rps <= 0:
            issues.append("NA_MAX_RPS must be > 0")
        return issues

    def problems_unofficial(self) -> List[str]:
        """Problems specific to the experimental export engine."""
        issues: List[str] = []
        if not self.notion_token_v2:
            issues.append(
                "NOTION_TOKEN_V2 is not set. The experimental export engine "
                "needs the `token_v2` cookie from a logged-in notion.so "
                "session (see docs/notion-token-setup.md)."
            )
        return issues

    def masked_token(self) -> str:
        tok = self.notion_token
        if not tok:
            return "(missing)"
        if len(tok) <= 12:
            return "***"
        return f"{tok[:7]}…{tok[-4:]} (len={len(tok)})"
