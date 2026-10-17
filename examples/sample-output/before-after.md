# Before → After: `Second Brain OS`

The demo source is a synthetic "paid template library" — nested pages, a
database, coloured callouts, a synced block, a template credit and duplicated
marketing copy. Below is the root page, before and after `na transform`.

## Before — 16 top-level blocks

Page title `🚀 【付费】Second Brain OS ★`, page icon `🎁`.

| # | Block | Detail |
|---|---|---|
| 1 | `heading_1` | "Welcome aboard" — **text colour `red`** |
| 2 | `table_of_contents` | |
| 3 | `breadcrumb` | |
| 4 | `paragraph` | "This operating system will 10x your productivity." ×3 — **`gray_background`** |
| 5 | `paragraph` | "Buy the full course" |
| 6 | `paragraph` | "Buy the full course" — **exact duplicate of #5** |
| 7 | `synced_block` | › `callout` "Synced module: weekly review" › `to_do` "Review inbox" |
| 8 | `heading_2` | "Weekly review" |
| 9 | `bulleted_list_item` | "Collect" › `paragraph` "empty the inbox" |
| 10 | `numbered_list_item` | "Clarify" |
| 11 | `code` | `make review`, language `bash` |
| 12 | `table` | 3 columns × 2 rows (Area / Cadence / Owner) |
| 13 | `image` | `https://example.com/remote-cover.png` |
| 14 | `image` | `diagram.png` |
| 15 | `bookmark` | `https://example.com/course` |
| 16 | `link_to_page` | mention of the child page |

Plus a database with 3 properties (`Task` title, `Area` select, `Done`
checkbox) and 2 rows.

## After — 13 top-level blocks

Page title `Second Brain OS`, icon re-picked deterministically.

| # | Block | What changed |
|---|---|---|
| 1 | `callout` | **new** — provenance card: source URL, extract timestamp, engine, source block count |
| 2 | `heading_2` | #1 demoted **H1 → H2** (the page title is already the H1); `red` colour stripped |
| 3 | `paragraph` | `gray_background` stripped |
| 4 | `paragraph` | "Buy the full course" — **one copy kept, duplicate removed** |
| 5 | `callout` | #7 `synced_block` **unwrapped** into a plain callout |
| 6 | `to_do` | preserved, still unchecked |
| 7 | `heading_2` | unchanged |
| 8 | `bulleted_list_item` | unchanged, child preserved |
| 9 | `numbered_list_item` | unchanged |
| 10 | `code` | unchanged |
| 11 | `table` | unchanged, all cells preserved |
| 12 | `image` | remote cover unchanged |
| 13 | `image` | local asset re-referenced to the downloaded copy |

Gone: `table_of_contents`, `breadcrumb`, `synced_block` wrapper, one duplicate
paragraph. Everything else survives — nothing is silently dropped.

## Numbers, straight from `transform-report.json`

```
blocks_in  23  →  blocks_out  22
dropped            table_of_contents 1 · breadcrumb 1 · synced_block 1 · ai_block 1
colors_stripped    2
icons_retuned      3
titles_normalized  2
h1_demoted         2
duplicates_removed 1
cards_added        3
```

`blocks_in`/`blocks_out` count **recursively** (children included), which is
why they are larger than the top-level counts above.

## Full exported page

[`markdown/second-brain-os.md`](markdown/second-brain-os.md)
