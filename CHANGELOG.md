# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Extract** — recursive Notion page-tree reader via the official API
  (blocks, nested children, databases, assets) with an *experimental*
  unofficial export fallback (`token_v2`) for view-only pages.
- **Transform** — special-marker cleansing, icon retuning, layout
  normalisation (heading levels, TOC, list cleanup) and metadata rewrite.
- **Publish** — chunked, rate-limited, resumable writer that rebuilds pages
  in your own Notion workspace with idempotent state tracking.
- **Markdown export** — clean, import-ready Markdown + assets bundle.
- **Demo mode** — full pipeline on built-in mock data, no credentials needed.
- CLI (`notion-alchemist` / `na`) with `extract` / `transform` / `publish` /
  `export-md` / `run` / `demo` / `doctor` subcommands.
- Test suite (`tests/`) with a zero-dependency runner
  (`python scripts/run_tests.py`) alongside the pytest path.
- Documentation: token tutorial, architecture, transform rules, FAQ, and a
  generated CLI reference.
- Wrapper scripts (`scripts/na.sh`, `scripts/na.ps1`) for running from a
  checkout without installing.
- Docker image, docker-compose deployment, `.dockerignore`.
- Agent Skill packaging (`SKILL.md` + `scripts/` + `references/` + `assets/`).

### Fixed
- `Document.count_blocks()` double-counted child pages (page blocks were
  counted once via the parent's recursion and again via their own
  iteration); now page-level blocks are counted exactly once.
- `publish_document` now requires a parent page and feeds an explicitly
  passed `parent_page_id` back into settings, so library callers get the
  same validation the CLI applies.
- Markdown export indents paragraphs nested inside list items, and prefers
  the bundled local asset over the (expiring) signed URL for images.
- Table rows are no longer dropped by the transform's empty-block check
  (their content lives in `cells`, not `text`).
- CLI state file (`.na_state.json`) now defaults to the `--output` directory
  instead of the current working directory, so each run is self-contained.

[0.1.0] - 2026-10-18

### Added
- Initial public scaffolding of the project.
