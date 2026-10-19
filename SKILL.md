---
name: notion-alchemist
description: >-
  Extract, cleanse, restructure and re-publish Notion content the user is
  authorised to access, into the user's own workspace. Use when the user wants
  to copy or clone a Notion page into their own space, convert a Notion page
  tree into an import-ready Markdown knowledge base, strip template credits /
  synced-block markers / watermark-ish text, normalise icons and heading
  hierarchy across many pages, or archive and re-layout a Notion library.
  Triggers: "extract this Notion page", "clone this Notion template into my
  workspace", "turn this Notion library into Markdown", "remove template
  watermarks", "reorganise my Notion pages", "Notion 提取", "Notion 克隆",
  "把 Notion 页面搬到我的空间", "Notion 导出 Markdown", "批量整理 Notion 页面".
license: MIT
compatibility: Requires Python >= 3.9 and the `requests` package for network
  stages (extract/publish). The demo, transform and export-md stages run with
  the standard library alone.
---

# Notion Alchemist

Turn any Notion page **you are authorised to access** into a clean,
re-publishable archive under your own structure: **Extract → Transform →
Publish**, as a local-first CLI.

## Golden rules

1. **Always drive the CLI — never improvise Notion API calls.** The CLI
   encodes rate limiting, chunking, retry semantics and resumable state that
   are easy to get wrong by hand.
2. **Dry-run before any real publish.** `na publish --dry-run` plans the whole
   write-back without touching Notion. Show the plan to the user first.
3. **Never handle credentials yourself.** Do not ask the user to paste tokens
   into chat. Point them at `docs/notion-token-setup.md` and let them fill
   `.env` themselves. Never echo, log or commit token values.
4. **Only extract content the user is authorised to access**, and respect the
   source's licence and Notion's Terms of Use. This tool automates manual
   work; it does not bypass permissions. Do not use it to redistribute
   paywalled or licensed material.
5. **Treat `NOTION_TOKEN_V2` as a password.** It is a logged-in session
   cookie, not an API key: whoever holds it is logged in as the user. Never
   echo it, never write it into a file other than the user's own `.env`, and
   prefer the official-API engine whenever the page can be shared with an
   integration.
6. **Respect the two-project boundary.** Feishu/Lark extraction is a separate
   project — do not extend this tool for it.

## Environment check (run first)

```bash
python -m notion_alchemist.cli doctor        # or: na doctor
```

Exit `0` = ready. Exit `2` = fixable config problem (token/paths) — read the
printed hints, they name the exact fix. `requests` missing is fine for
demo/transform/export-md, but required for extract/publish.

Before publishing this skill anywhere, also run the packaging self-check:

```bash
python scripts/skillhub_preflight.py         # 12-item check, exit 0/1/2
```

## Intent → command map

| User wants… | Run |
|---|---|
| See what the tool does, no credentials | `na demo -o examples/demo_output` |
| Pull a page tree into IR | `na extract <url> -o output` |
| Only reachable via view-only/guest access | `na extract <url> --engine export` (experimental; needs `NOTION_TOKEN_V2`) |
| Cleanse / retune icons / relayout an existing IR | `na transform output/structure.json -o output` |
| Rebuild in the user's own Notion | `na publish output/transformed.json --parent <id-or-url>` — **always `--dry-run` first** |
| Copy into Feishu/Lark Docs instead | `na publish-feishu output/transformed.json` — **always `--dry-run` first**; needs `NA_FEISHU_APP_ID` + `NA_FEISHU_APP_SECRET` |
| Everything in one shot | `na run <url> --parent <id-or-url>` |
| Markdown bundle instead of Notion pages | `na run <url> --md-only` or `na export-md output/transformed.json` |
| Resume an interrupted publish | just re-run the same `publish` / `publish-feishu` command — the state file makes it idempotent |
| Parse an already-downloaded export ZIP | `na extract <url> --engine export --zip path/to.zip` |

## Stage outputs (all plain JSON — inspectable, scriptable, versionable)

```
output/
├── structure.json          # canonical IR straight from Extract
├── extract-report.json     # engine, page/block counts, stats
├── transformed.json        # IR after Transform (the publish input)
├── transform-report.json   # what was dropped / stripped / retuned
├── publish-report.json     # pages created, blocks appended, errors
├── publish-feishu-report.json  # documents created/reused, blocks, errors
├── markdown-report.json    # bundle stats (export-md)
├── .na_state.json          # Notion publish resume state
├── .na_feishu_state.json   # Feishu publish resume state
├── assets/                 # images & files pulled at extract time
└── bundle/                 # import-ready Markdown (export-md)
```

## Transform defaults (what "make it yours" means)

Dropped: `table_of_contents`, `breadcrumb`, `template`, `ai_block`,
`unsupported` blocks; exact-duplicate sibling blocks; empty blocks.
Stripped: all text/background colours. Demoted: H1 → H2 (the page title is
already the H1). Icons: deterministically re-picked from a fixed emoji set
(`--icon-mode keep|retune|none`). Titles: emoji/brand/bracket prefixes removed.
Every page gets a provenance callout (`--no-archive-card` to disable).

Every default has an escape hatch: `--keep-noise`, `--keep-colors`,
`--keep-titles`, `--keep-h1`, `--keep-duplicates`.

## Failure handling

- `exit 2` → configuration problem. The message names the fix; `doctor`
  gives the full picture.
- `exit 1` → runtime failure. Re-run with `-v` for the traceback.
- Publish interrupted (Ctrl-C / network drop) → progress is saved; re-run the
  identical command to resume. Never restart from scratch — that would
  duplicate pages.
- `503` with `retry_guidance: do_not_retry` means the write **landed**; the
  CLI surfaces it instead of replaying. Trust the state file.

## References

- [docs/index.md](docs/index.md) — annotated index of all docs, with language tags
- `docs/notion-token-setup.md` — credential setup, step by step (zh)
- `docs/notion-token-setup.en.md` — same, in English
- `docs/architecture.md` — IR shape, engines, write-back strategy (zh)
- `docs/architecture.en.md` — same, in English
- `docs/transform-rules.md` — every transform rule with before/after examples (zh)
- `docs/faq.md` — common problems (zh)
- `examples/sample-output/` — committed before/after sample, no install needed
- `references/cli-reference.md` — full CLI surface
