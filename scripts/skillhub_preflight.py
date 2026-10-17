#!/usr/bin/env python3
"""SkillHub pre-flight self-check.

Mirrors the 12-item pre-flight checker documented at skillhub.cn, so you can
find problems before an upload instead of after a rejection.

Usage:
    python scripts/skillhub_preflight.py            # check this repo
    python scripts/skillhub_preflight.py <path>     # check another skill dir

Exit codes (same convention as the documented checker):
    0  ready to upload
    1  risks present — review the warnings
    2  will be rejected — fix the errors first
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_FRONTMATTER = ("name", "description", "license", "compatibility")
# Fields the spec allows at the top level; anything else is flagged, not fatal.
KNOWN_TOP_LEVEL = REQUIRED_FRONTMATTER + ("metadata", "allowed-tools", "version")

# Words that make a slug generic and therefore collision-prone.
GENERIC_SLUG_WORDS = {
    "tool", "tools", "helper", "helpers", "util", "utils", "utility",
    "skill", "skills", "agent", "assistant", "manager", "manager", "kit",
    "box", "suite", "app", "application", "library", "lib", "framework",
    "common", "general", "misc", "test", "demo", "example", "sample",
}

# Credential-shaped literals that must never appear in a shipped skill.
SECRET_PATTERNS = [
    (re.compile(r"\bntn_[A-Za-z0-9]{20,}"), "Notion integration token (ntn_...)"),
    (re.compile(r"\bsecret_[A-Za-z0-9]{20,}"), "Notion legacy token (secret_...)"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI-style API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"(?i)\b(bearer|authorization)\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{20,}"),
     "Authorization header value"),
]

# A CN mobile number, the classic "sensitive residue".
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# Directories whose contents are fixtures, not shipped payload. A checker that
# scans its own tests will flag its own deliberately-fake tokens — the exact
# false-positive class that makes people stop trusting the checker.
SKIP_DIRS = {"tests", "fixtures", "test", "__pycache__", ".git", "node_modules",
             ".venv", "venv", ".pytest_cache", ".ruff_cache", "dist", "build"}


# Trigger phrases we expect in the description: at least 3 concrete scenarios
# and both Chinese and English coverage.
MIN_SCENARIOS = 3


def _read_frontmatter(text: str):
    """Return (frontmatter_text, body) or (None, text) when absent."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    return text[3:end], text[end + 4:]


def _parse_simple_yaml(block: str):
    """Minimal YAML subset parser: top-level scalars and folded blocks."""
    data: dict[str, str] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[:1] in (" ", "\t"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()
        if rest in (">", ">-", "|", "|-"):
            # folded / literal block: consume the indented continuation
            buf: list[str] = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            data[key] = " ".join(x for x in buf if x)
        else:
            data[key] = rest.strip("'\"")
            i += 1
    return data


def check(root: Path) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # ---- 1. directory structure -------------------------------------------
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        print(f"[error] 1. SKILL.md not found at package root: {skill_md}")
        return 2
    print(f"[ok]    1. SKILL.md present at package root")

    text = skill_md.read_text(encoding="utf-8")

    # ---- 2. required frontmatter fields -----------------------------------
    fm_raw, body = _read_frontmatter(text)
    if fm_raw is None:
        print("[error] 2. SKILL.md has no YAML frontmatter block")
        return 2
    fm = _parse_simple_yaml(fm_raw)
    missing = [f for f in REQUIRED_FRONTMATTER if not fm.get(f)]
    if missing:
        errors.append(f"2. frontmatter missing required field(s): {', '.join(missing)}")
    else:
        print(f"[ok]    2. required frontmatter fields present: "
              f"{', '.join(REQUIRED_FRONTMATTER)}")
    extra = [k for k in fm if k not in KNOWN_TOP_LEVEL]
    if extra:
        warnings.append(f"2. non-standard top-level frontmatter key(s): {', '.join(extra)}")

    name = fm.get("name", "")
    desc = fm.get("description", "")

    # ---- 3. name == directory name ----------------------------------------
    if name and name != root.name:
        errors.append(f"3. frontmatter name {name!r} != directory name {root.name!r}")
    else:
        print(f"[ok]    3. name matches directory: {name}")

    # ---- 4. slug collisions (generic words) -------------------------------
    words = set(re.split(r"[-_\s]+", name.lower())) - {""}
    generic = words & GENERIC_SLUG_WORDS
    if generic:
        errors.append(f"4. slug contains generic word(s): {', '.join(sorted(generic))}")
    elif name:
        print(f"[ok]    4. slug is specific: {name}")

    # ---- 5. sensitive residue ---------------------------------------------
    def _scannable(path: Path) -> bool:
        return not any(part in SKIP_DIRS for part in path.relative_to(root).parts)

    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _scannable(path):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip",
                                   ".pdf", ".woff", ".woff2", ".ttf"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(content):
                hits.append(f"{rel}: {label}")
        for m in PHONE_RE.finditer(content):
            hits.append(f"{rel}: phone-number-shaped literal {m.group(0)}")
    if hits:
        errors.append("5. sensitive residue -> " + "; ".join(hits))
    else:
        print("[ok]    5. no credential/phone residue in shipped text files")

    # absolute paths (outside of examples that explicitly show them)
    abs_hits: list[str] = []
    for path in sorted(root.rglob("*.md")):
        if not _scannable(path):
            continue
        content = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?<![\w./-])[A-Za-z]:\\\\[^\s\"'`)]+|(?<![\w.~])/home/\w+/|(?<![\w.~])/Users/\w+/",
                             content):
            abs_hits.append(f"{path.relative_to(root).as_posix()}: {m.group(0)}")
    if abs_hits:
        warnings.append("5. absolute path(s) in docs: " + "; ".join(abs_hits[:5]))
    else:
        print("[ok]    5. no absolute filesystem paths in markdown")

    # ---- 6. encoding safety ------------------------------------------------
    non_ascii_names = [p.name for p in root.rglob("*")
                       if p.name and not p.name.isascii()]
    if non_ascii_names:
        warnings.append(
            f"6. non-ASCII filename(s) present: {', '.join(sorted(set(non_ascii_names))[:5])} "
            "— when zipping, force UTF-8 filename encoding (Python zipfile does this by "
            "default; some GUI archivers do not)")
    else:
        print("[ok]    6. all filenames are ASCII")

    # ---- 7. description quality -------------------------------------------
    problems: list[str] = []
    if len(desc) < 40:
        problems.append(f"description too short ({len(desc)} chars)")
    has_cn = bool(re.search(r"[\u4e00-\u9fff]", desc))
    has_en = bool(re.search(r"[A-Za-z]{3,}", desc))
    if not has_cn:
        problems.append("description has no Chinese triggers")
    if not has_en:
        problems.append("description has no English triggers")
    quoted = re.findall(r"[\"'`]([^\"'`]{6,80})[\"'`]", desc)
    if len(quoted) < MIN_SCENARIOS:
        problems.append(
            f"only {len(quoted)} quoted trigger phrase(s); want >= {MIN_SCENARIOS}")
    if problems:
        errors.append("7. description quality -> " + "; ".join(problems))
    else:
        print(f"[ok]    7. description: {len(desc)} chars, "
              f"{len(quoted)} trigger phrases, bilingual")

    # ---- 8. dependency declaration ----------------------------------------
    compat = fm.get("compatibility", "")
    if "python" not in compat.lower() and "node" not in compat.lower() \
            and "runtime" not in compat.lower():
        errors.append("8. compatibility does not declare a runtime")
    else:
        print("[ok]    8. runtime declared in compatibility")

    # ---- 9. boundary honesty ----------------------------------------------
    honesty = 0
    for kw in ("experimental", "authorised", "authorized", "separate project",
               "not guaranteed", "no guarantee"):
        if kw in body.lower():
            honesty += 1
    if honesty < 2:
        warnings.append(
            f"9. body mentions only {honesty} boundary marker(s) "
            "(experimental / authorised access / separate project) — reviewers read "
            "vague boundaries as overclaiming")
    else:
        print(f"[ok]    9. boundary markers in body: {honesty}")

    # ---- 10. references resolve -------------------------------------------
    broken: list[str] = []
    for m in re.finditer(r"`([^`\n]+\.md)`", body):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://")):
            continue
        if not (root / target).exists():
            broken.append(target)
    if broken:
        warnings.append(f"10. referenced file(s) not found: {', '.join(sorted(set(broken)))}")
    else:
        print("[ok]    10. every `*.md` reference in the body resolves")

    # ---- 11. scripts referenced actually exist ----------------------------
    script_refs = set(re.findall(r"`(scripts/[^`\s]+)`", body))
    missing_scripts = [s for s in script_refs if not (root / s).exists()]
    if missing_scripts:
        errors.append(f"11. referenced script(s) missing: {', '.join(missing_scripts)}")
    else:
        print(f"[ok]    11. {len(script_refs)} referenced script(s) all exist")

    # ---- 12. no dead CLI surface ------------------------------------------
    cli_doc = root / "references" / "cli-reference.md"
    if cli_doc.is_file():
        print("[ok]    12. CLI reference present")
    else:
        warnings.append("12. no references/cli-reference.md — the CLI surface is undocumented")

    # ---- report ------------------------------------------------------------
    print()
    for w in warnings:
        print(f"[warn]  {w}")
    for e in errors:
        print(f"[error] {e}")
    if notes:
        for n in notes:
            print(f"[note]  {n}")

    if errors:
        print(f"\nRESULT: exit 2 — {len(errors)} error(s), {len(warnings)} warning(s). "
              "This would be rejected.")
        return 2
    if warnings:
        print(f"\nRESULT: exit 1 — {len(warnings)} warning(s). Reviewable, but fix what you can.")
        return 1
    print("\nRESULT: exit 0 — ready to upload.")
    return 0


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    print(f"SkillHub pre-flight check: {root}\n")
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
