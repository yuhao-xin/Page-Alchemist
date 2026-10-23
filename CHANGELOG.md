# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Known follow-ups
- **PEP 585/604 modernisation** — `typing.List`/`Dict` → `list`/`dict` and
  `Optional[X]` → `X | None` across ~280 annotations. Not enabled by the
  pinned ruff set on purpose: `X | None` is only safe where annotations are
  postponed, and the declared floor is still Python 3.9. Do it as its own
  pass, in its own commit.

## [0.2.1] - 2026-10-24

Maintenance release: makes the shipped checks pass *outside* a directory that
happens to be named after the package — which is what a CI checkout is.

### Fixed
- **CI was red on every commit.** The SkillHub pre-flight compared the
  `SKILL.md` name to the *directory* name verbatim, so a checkout directory
  named after the repository (`Page-Alchemist`) failed item 3 with exit 2 —
  failing all three CI jobs, including the test job that runs the same check
  as a regression guard. The check now compares normalised slugs and also
  accepts the name the project declares for itself in `pyproject.toml` /
  `setup.cfg` / `setup.py`; an unrelated directory name with no matching
  declaration is still an error.
- Unused imports in `src/` and `tests/` cleared, and the ruff rule set pinned
  in `pyproject.toml` (`[tool.ruff.lint] select`), so `ruff check` — which had
  never actually run, the test step failed first — passes. The pin matters:
  ruff's implicit default grew in the 0.14+ releases, so an unpinned
  `ruff>=0.6` turned CI red with ~300 findings unrelated to the commit.

### Added
- Regression tests locking the new behaviour: a checkout directory whose name
  differs from the package is accepted when the project declares that name,
  and rejected when it does not.

## [0.2.0] - 2026-10-24

The release that makes the tool **output-agnostic**: Notion is still the only
extraction source, but the cleaned tree can now be rebuilt in Notion *or*
Feishu/Lark Docs, or exported as an import-ready Markdown bundle.

### Added
- **Feishu / Lark publish target** — `na publish-feishu` copies the cleaned
  tree into Feishu docx documents (one document per source page, sub-pages as
  siblings with the hierarchy preserved in a provenance callout), with
  tenant-token auth, ≤100-block descendant batches, local image upload,
  resumable `.na_feishu_state.json` and `--dry-run`.
- **Extract** — recursive Notion page-tree reader via the official API
  (blocks, nested children, databases, assets) with an *experimental*
  unofficial export fallback (`token_v2`) for view-only pages.
- **Transform** — special-marker cleansing, icon retuning, layout
  normalisation (heading levels, TOC, list cleanup) and metadata rewrite.
- **Publish** — chunked, rate-limited, resumable writer that rebuilds pages
  in your own Notion workspace with idempotent state tracking.
- **Markdown export** — clean, import-ready Markdown + assets bundle.
- **Demo mode** — full pipeline on built-in mock data, no credentials needed.
- CLI (`page-alchemist` / `na`) with `extract` / `transform` / `publish` /
  `publish-feishu` / `export-md` / `run` / `demo` / `doctor` subcommands.
- Test suite (`tests/`) with a zero-dependency runner
  (`python scripts/run_tests.py`) alongside the pytest path — **159 tests**.
- Documentation: token tutorial, architecture, transform rules, FAQ, Feishu
  publish tutorial, and a generated CLI reference.
- Wrapper scripts (`scripts/na.sh`, `scripts/na.ps1`) for running from a
  checkout without installing.
- Docker image, docker-compose deployment, `.dockerignore`.
- Agent Skill packaging (`SKILL.md` + `scripts/` + `references/` + `assets/`).
- English documentation: `docs/notion-token-setup.en.md`,
  `docs/architecture.en.md` and `docs/feishu-publish.en.md`, plus
  `docs/index.md` (annotated index with language tags) so non-Chinese readers
  can reach the highest-friction docs.
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
  the shipped repository itself must score exit `0`.

### Changed
- **Renamed** `notion-alchemist` → `page-alchemist` (package
  `notion_alchemist` → `page_alchemist`): the tool is no longer Notion-only on
  the output side. The `na` command is unchanged. Repository-level follow-up:
  rename the GitHub repository in *Settings → General → Repository name*;
  GitHub then redirects the old URL automatically, and every
  `github.com/yuhao-xin/page-alchemist` link in these docs starts resolving.
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
- Roadmap items re-numbered (v0.2 was taken by this release; the duplicate
  engine is now v0.3).

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
- `.na_feishu_state.json` added to `.gitignore` — the Feishu resume state sat
  next to the Notion one but was not ignored, so a run from the repository
  root could commit document-id mappings.

## [0.1.0] - 2026-10-18

### Added
- Initial public scaffolding of the project.
