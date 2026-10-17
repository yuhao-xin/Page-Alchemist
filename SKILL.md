---
name: notion-alchemist
description: >-
  Extract, cleanse, restructure and re-publish Notion content into the user's
  own workspace. Use when the user wants to copy/clone/archive a Notion page
  they have access to, convert a private or paid Notion library into their own
  public free knowledge base, strip synced-block/template markers and retune
  icons, or export Notion content as import-ready Markdown. Triggers:
  "extract this Notion page", "clone this Notion template", "copy Notion to my
  workspace", "Notion 提取", "Notion 克隆", "把 Notion 页面搬到我的空间",
  "Notion 导出 Markdown".
license: MIT
compatibility: Requires Python >= 3.9 and the `requests` package for network
  stages (extract/publish). The demo, transform and export-md stages run with
  the standard library alone.
---

# Notion Alchemist

Turn any Notion page you can access into *your own* knowledge base:
**Extract → Transform → Publish**, as a local-first CLI.

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
   work; it does not bypass permissions.
5. **Respect the two-project boundary.** Feishu/Lark extraction is a separate
   project — do not extend this tool for it.

## Environment check (run first)

```bash
python -m notion_alchemist.cli doctor        # or: na doctor
```

Exit `0` = ready. Exit `2` = fixable config problem (token/paths) — read the
printed hints, they name the exact fix. `requests` missing is fine for
demo/transform/export-md, but required for extract/publish.

## Intent → command map

| User wants… | Run |
|---|---|
| See what the tool does, no credentials | `na demo -o examples/demo_output` |
| Pull a page tree into IR | `na extract <url> -o output` |
| Only reachable via view-only/guest access | `na extract <url> --engine export` (experimental; needs `NOTION_TOKEN_V2`) |
| Cleanse / retune icons / relayout an existing IR | `na transform output/structure.json -o output` |
| Rebuild in the user's own Notion | `na publish output/transformed.json --parent <id-or-url>` — **always `--dry-run` first** |
| Everything in one shot | `na run <url> --parent <id-or-url>` |
| Markdown bundle instead of Notion pages | `na run <url> --md-only` or `na export-md output/transformed.json` |
| Resume an interrupted publish | just re-run the same `publish` command — `.na_state.json` makes it idempotent |
| Parse an already-downloaded export ZIP | `na extract <url> --engine export --zip path/to.zip` |

## Stage outputs (all plain JSON — inspectable, scriptable, versionable)

```
output/
├── structure.json          # canonical IR straight from Extract
├── extract-report.json     # engine, page/block counts, stats
├── transformed.json        # IR after Transform (the publish input)
├── transform-report.json   # what was dropped / stripped / retuned
├── publish-report.json     # pages created, blocks appended, errors
├── markdown-report.json    # bundle stats (export-md)
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

- `docs/notion-token-setup.md` — credential setup, step by step
- `docs/architecture.md` — IR shape, engines, write-back strategy
- `docs/transform-rules.md` — every transform rule with before/after examples
- `docs/faq.md` — common problems
- `references/cli-reference.md` — full CLI surface
