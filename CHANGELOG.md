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
- English documentation: `docs/notion-token-setup.en.md` and
  `docs/architecture.en.md`, plus `docs/index.md` (annotated index with
  language tags) so non-Chinese readers can reach the two highest-friction
  docs.
- `examples/sample-output/` — a trimmed, **committed** copy of a real
  `na demo` run (before/after walkthrough + machine-readable reports), so the
  output is judgeable without installing anything.
- `docs/pm-review.md` — product-manager review plus a cross-check against the
  SkillHub evaluation rubrics (skillhub.club six-dimension weights and
  skillhub.cn TRACE five-dimension model with its 12-item pre-flight checker).
- API-version migration policy documented in `docs/architecture.md` /
  `architecture.en.md`: why `2022-06-28` is pinned, the three trigger
  conditions for migrating, and the mechanical migration procedure.
- `scripts/skillhub_preflight.py` — a 12-item pre-flight self-check mirroring
  the SkillHub checker (directory structure, frontmatter fields, name/directory
  agreement, slug collisions, credential & phone residue, ASCII filenames,
  description quality, dependency declaration, boundary honesty, reference
  resolution, script existence, CLI reference). Exits `0` / `1` / `2` on the
  same convention as the platform. Wired into `make preflight` and a dedicated
  CI job. `tests/` and `fixtures/` are excluded from the residue scan, because
  a checker that scans its own tests flags its own fake tokens.
- 19 new tests (`tests/test_skillhub_preflight.py`) covering both the
  checker's detection logic and its parsing, including a regression guard that
  the shipped repository itself must score exit `0`. Suite is now 132 tests.

### Changed
- **Positioning rewritten.** The "private → yours, paid → free" framing is
  replaced throughout (`README.md`, `README.zh-CN.md`, `SKILL.md`) with
  "content you are authorised to access → a clean, re-publishable archive
  under your own structure". The tool's contract is unchanged: you bring the
  access rights, it automates what you could do by hand — but the copy no
  longer reads as a paywall-bypass tool.
- `SKILL.md` description expanded from 2 to 4 intent families with bilingual
  triggers (clone-into-workspace, Notion→Markdown knowledge base, marker /
  watermark stripping, bulk page normalisation).
- `NOTION_TOKEN_V2` is now documented as a **password-equivalent** credential
  in `SKILL.md` (golden rule 5) and both READMEs, with an explicit preference
  for the official-API engine whenever the page can be shared with an
  integration.

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
