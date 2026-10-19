# Architecture

## In one sentence

**Page Alchemist = a three-stage pipeline over a canonical intermediate
representation (IR) that lives on disk.** Extract → Transform → Publish, with
stages passing only two plain-JSON files: `structure.json` and
`transformed.json`.

```
 Notion URL ──► ┌──────────┐   structure.json   ┌───────────┐  transformed.json
                │ Extract  │ ─────────────────► │ Transform │ ───────────────┐
                │ api/export│                    │ cleanse…  │               │
                └──────────┘                    └───────────┘               │
                     │ assets/                        │                     ▼
                     │                          ┌─────┴──────┐      ┌───────────┐
                     │                          │            │      │  Publish  │──► your Notion
                     │                          ▼            ▼      │ (chunked │
                     │                    publish-report  export-md │ resumable│
                     │                                       │      └───────────┘
                     └──► output/assets/ ◄───────────────────┘            │
                                                                    Markdown bundle
```

## Why files between stages instead of in-memory objects

1. **Interruptible and re-runnable.** Extracting 500 pages takes tens of
   minutes; if any step dies, you resume from the JSON on disk without
   re-extracting (Notion file URLs expire after an hour, but assets are
   already on disk from extract time).
2. **Auditable.** `structure.json` is a complete snapshot of "what is actually
   in this library"; diffing two versions shows what changed in the source.
3. **Scriptable.** Re-run publish alone without touching transform, or feed
   `transformed.json` into your own renderer.

## IR (Intermediate Representation)

Defined in `src/page_alchemist/models.py` — four dataclasses:

| Type | Key fields | Notes |
|---|---|---|
| `Document` | `source_url, engine, extracted_at, pages[], stats` | archive root |
| `PageNode` | `source_id, title, icon, cover, blocks[], children[], database` | a page; `children` are child pages; `database` present means this page is a database view |
| `Block` | `type, text[], children[], cells[], asset, raw, checked, language, url` | a block; `text`/`cells` are `RichText[]`; `raw` keeps the original API payload |
| `RichText` | `text, kind, bold, italic, …, color, link` | the smallest text unit |

Design trade-offs:

- **Keep `raw`.** When parsing fails or Notion adds new block types, no
  information is lost and an upgrade cannot destroy data.
- **Tables use `cells`.** A `table_row`'s content lives in cells, not `text`;
  missing that layer silently loses data (we hit this — see `tests`).
- **`asset.local_path`.** Notion file URLs are signed and expire after about
  an hour, so assets are downloaded at extract time and the IR records only
  the local path.

## Extract: two engines

### Engine A — official API (default, stable)

`notion_api.py`. Recursively pulls `GET /v1/blocks/{id}/children`. Key points:

- **`Notion-Version` pinned to `2022-06-28`** — the widest compatibility
  surface, and everything this tool uses (pages / blocks / databases) is
  present in that version. (Since 2025-09-03 Notion renamed *database* to
  *data source* and changed fields, so we deliberately do not chase the new
  version.)
- **Rate limiting** — token bucket at ~3 req/s, honouring `Retry-After` on
  `429`.
- **Assets download during extraction** into `output/assets/`, deduplicated by
  sha1.
- **Depth cap of 12 levels** — stops a pathological tree from blowing the
  recursion.

### Engine B — export fallback (experimental)

`notion_unofficial.py`. For pages you can only **view** (e.g. a guest link to
a paid template library), the official API cannot reach them — there is no way
to "share" the page with an integration.

The approach: call Notion's internal web task endpoint
`POST /api/v3/enqueueTask` (`eventName: "exportBlock"`, `exportType:
"markdown"`) → poll `getTasks` → download the signed ZIP → parse. It is
equivalent to clicking *Export → Markdown & CSV* in the browser, automated.
`parse_export_zip` then restores the Markdown/CSV/image tree into **exactly
the same IR** as Engine A — nothing downstream can tell the difference.

- Requires `NOTION_TOKEN_V2` (a logged-in session cookie), see
  [notion-token-setup.en.md](notion-token-setup.en.md).
- Depends on a Notion-internal web endpoint that may change at any time —
  hence *experimental*, with no long-term guarantee. **If Engine A can reach
  the page, use Engine A.**
- Also accepts `--zip` to parse an export archive you downloaded by hand —
  fully offline.

## Transform: making the content yours

`transform.py`. All rules on by default, each with an escape hatch:

| Rule | Default | Flag | Notes |
|---|---|---|---|
| De-noise | ✅ drop `table_of_contents` / `breadcrumb` / `template` / `ai_block` / `unsupported` | `--keep-noise` | navigation traces from someone else's library |
| De-colour | ✅ | `--keep-colors` | all text/background highlight colours reset to default |
| Icon retune | ✅ deterministic emoji by sha1 | `--icon-mode keep\|retune\|none` | same title always yields the same icon — reproducible |
| Title normalisation | ✅ | `--keep-titles` | strips emoji / brand prefixes / bracket decoration |
| H1 demotion | ✅ | `--keep-h1` | the page title is already the H1, so body H1s become H2 |
| De-duplication | ✅ adjacent identical blocks | `--keep-duplicates` | placeholder paragraphs copied around a template |
| Provenance card | ✅ callout at the top of every page | `--no-archive-card` | records source URL, engine, extract time, section outline |

`synced_block` is **unwrapped** for its content — a synced block is a
cross-page linking mechanism, and once the content moves into your own space
that link should be severed.

## Publish: writing back into your own Notion

`publish.py`. This is the most fragile part of the project; the core decisions:

### 1. Flat appends, never nested

Notion's `children.append` allows **at most 2 levels of nesting per request**,
at most 100 blocks per request, a 1000-block overall cap, and a 500 KB body
cap. If you write it the intuitive way — "one page, one request, whole
subtree" — even a moderately deep tree hits the wall, and the error message
rarely tells you which block was at fault.

This tool instead **appends only top-level blocks first, then appends child
content level by level using the returned block IDs** (`_append_units` →
`_append_kids`, recursive). The 2-level limit is fully sidestepped, every
payload is flat, and a failure points at exactly one block.

### 2. Chunking + failure isolation

Each batch is ≤100 payloads and ≤400 KB (20% headroom). When a batch fails it
is **bisected** to locate the problem, discarding only the genuinely broken
block while the rest continue — one malformed block cannot take down a page.

### 3. Resume from a state file

`.na_state.json` (written atomically) records each page's created ID, the
number of payloads appended, the database schema, and the number of rows
inserted. After an interruption, **re-running the same command resumes**:

- page already exists → reuse it, do not create a duplicate
- N payloads already appended → reconcile against the live child count, then
  continue
- M database rows already inserted → continue from row M+1

> Reconciliation detail: `units_appended` counts **top-level payloads**; if the
> page materialises a database, the live child count is appended + 1 (the
> database itself is also a block).

### 4. The semantics of 503

Notion returns `503` with `retry_guidance: do_not_retry` for a write that has
already landed but whose response timed out. Blindly retrying produces
**duplicate content**. The tool reports such a response to the caller and
records it in the state file, letting the resume logic reconcile; it never
auto-replays.

### 5. Icon strategy

Transform decides `node.icon`; Publish only applies it — policy and execution
are separated, so changing icon rules never touches the write code.

## export-md: the exit that skips Notion

`export_md.py` renders the IR into an **import-ready Markdown bundle**: one
`.md` per page (headings / lists / to-dos / quotes / callouts / code / tables
/ images all covered), databases to CSV, images copied into `assets/`, and an
`INDEX.md` roll-up. Useful when you only want clean content, or when you would
rather manage the content in Git first.

## demo: the full pipeline without credentials

`demo.py` ships a synthetic "🚀 【付费】Second Brain OS ★" template library
(nested pages, a database, a synced block, noise blocks, coloured text,
duplicate blocks, images) and pushes it through all three stages, producing
the full set of artefacts. A single `na demo` shows you the output shape of
every stage and **needs no token at all**.

## Module map

```
src/page_alchemist/
├── cli.py               # seven subcommands: extract/transform/publish/
│                        #   export-md/run/demo/doctor
├── config.py            # Settings: env/.env → validated by problems()
├── models.py            # IR dataclasses + JSON serialisation
├── util.py              # logging / rate limiting / backoff / slug / sha1 / dotenv / ID extraction
├── notion_api.py        # Engine A: official API extraction
├── notion_unofficial.py # Engine B: exportBlock fallback (experimental)
├── transform.py         # cleansing / icons / relayout / titles / provenance card
├── publish.py           # write-back: flat appends, chunking, resume, failure isolation
├── export_md.py         # Markdown bundle rendering
└── demo.py              # offline demo data and the full pipeline
```

## Dependency stance

At runtime the only dependency is **`requests`** (and only for the network
stages); transform / export-md / demo are pure standard library. pytest/ruff
are development-only. `--help`, `doctor` and `demo` all run in an environment
without `requests` installed — CI can validate before installing anything.

## Explicit non-goals

- **No Feishu/DingTalk extraction.** That is a separate project; the user
  explicitly asked for the split.
- **No in-place cloning.** On the v0.2 roadmap; needs `saveTransactions` and
  carries a high risk of tripping Notion's abuse controls.
- **Do not chase new API versions.** Stability over new features, unless the
  old version is officially deprecated.

## API version migration policy

`Notion-Version` is pinned to `2022-06-28`. This is a deliberate decision, not
neglect, but it needs a maintenance rule:

- **Why pinned.** The 2025-09-03 version renamed `database` to `data source`
  and restructured response fields. This tool's read path (blocks/children,
  databases) and write path (pages.create, children.append, data sources)
  are all verified against 2022-06-28 by the test suite.
- **When to migrate.** Migrate when **any** of these becomes true:
  1. Notion announces end-of-life for 2022-06-28 (they have not, as of this
    writing);
  2. a feature is needed that only exists in a newer version;
  3. a `validation_error` appears that cannot be explained by our own payload
    construction.
- **How to migrate.** The version string lives in one place (see
  `src/page_alchemist/`), so the change is mechanical: bump the constant,
  run the suite, then fix whatever the response-shape changes break. Because
  the IR keeps `raw`, existing archives on disk stay readable across the
  migration — you do not have to re-extract old sources.
- **What to watch.** The `database` → `data source` rename is the known
  breaking change; our `PageNode.database` field and the `parse_export_zip`
  CSV path are the two places most likely to need attention.
