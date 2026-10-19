# Feishu publish tutorial

> Audience: anyone who wants the cleansed output of notion-alchemist
> **copied into Feishu Docs**. ~10 minutes, no code. All you need is a
> Feishu **custom app** (App ID / App Secret) — no admin, no enterprise
> verification required.

---

## Contents

1. [What it does](#what-it-does)
2. [Step 1 — create the Feishu custom app](#step-1--create-the-feishu-custom-app)
3. [Step 2 — grant permissions](#step-2--grant-permissions)
4. [Step 3 — write .env](#step-3--write-env)
5. [Step 4 — dry-run](#step-4--dry-run)
6. [Step 5 — publish for real](#step-5--publish-for-real)
7. [Behaviour notes (read me)](#behaviour-notes-read-me)
8. [Error cheat-sheet](#error-cheat-sheet)
9. [Lark (international) users](#lark-international-users)
10. [Security notes](#security-notes)

---

## What it does

`na publish-feishu` turns `transformed.json` (the IR) into **Feishu docx
documents**:

- one Notion page → one Feishu document (title = page title)
- sub-pages → **sibling documents** in the same folder (Feishu has no API
  for a document nested inside a document; the hierarchy survives as a
  provenance callout at the top of each page)
- headings / paragraphs / lists / to-dos / code / quotes / callouts /
  dividers / bookmarks / tables map one-to-one; **local images are
  uploaded** as Feishu media
- inline databases → table blocks (truncated at 200 rows, noted in the
  report)
- progress lives in `.na_feishu_state.json`: **re-running never creates
  duplicate documents**

```bash
notion-alchemist publish-feishu output/transformed.json
```

---

## Step 1 — create the Feishu custom app

1. Sign in to Feishu and open <https://open.feishu.cn/app>
2. Click **Create custom app** (创建企业自建应用)
3. Name it (e.g. `Notion Alchemist`) and create it
4. In the app page, open **Credentials & Basic Info** and copy the
   **App ID** (`cli_…`) and **App Secret**

> ⚠️ A custom app must **publish a version** before its
> `tenant_access_token` works. If step 4 fails with `99991664` or any
> permission error, go to **Version Management & Release**, create a
> version and submit it for release (in-company apps are usually approved
> instantly).

---

## Step 2 — grant permissions

In **Permissions & Scopes**, add the minimum set:

| Scope | Used for |
|---|---|
| `docx:document` | create documents, write blocks |
| `drive:drive` | upload image media into a document |
| `drive:file:upload` | media upload (`medias/upload_all`) |

**Publish a new version again** — scopes only take effect after release.

---

## Step 3 — write .env

In `.env` at the project root (copy from `.env.example`):

```bash
NA_FEISHU_APP_ID=cli_xxxxxxxxxxxx
NA_FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
# optional: create documents inside a specific folder token
# NA_FEISHU_FOLDER=fldxxxxxxxxxxxx
```

With `NA_FEISHU_FOLDER` empty, documents land in the app's own Drive root
(a custom app has no "My Space" of its own). To find a folder token: open
the folder in the Feishu Drive web UI — the URL's last segment is the
`fld…` token.

---

## Step 4 — dry-run

```bash
notion-alchemist publish-feishu output/transformed.json --dry-run
```

The dry-run makes **no API calls** and needs no credentials, but prints
every document that would be created plus block counts. Continue when
`errors : 0`.

---

## Step 5 — publish for real

```bash
notion-alchemist publish-feishu output/transformed.json
```

Prints a link per document (`https://www.feishu.cn/docx/<id>`); the report
lands in `output/publish-feishu-report.json`.

Interrupted? **Re-run the same command**: fully written documents are
skipped, half-written ones are topped up in place — no duplicates.

---

## Behaviour notes (read me)

| Topic | Behaviour |
|---|---|
| Hierarchy | flattened to sibling documents; each page starts with a source callout (URL + page path) |
| Images | local file → uploaded media; remote-only → link paragraph (Feishu has no external-image block) |
| Code blocks | language mapped to the Feishu `CodeLanguage` enum; unknown → `PlainText` (highlighting only) |
| Tables | wider than 20 columns / 400 cells degrade to monospaced text lines |
| Databases | rendered as a table, max 200 rows, overflow noted in report `skipped` |
| Colours | not preserved (transform strips them by default, same as the Notion writer) |
| Synced blocks / columns | unwrapped into sequential content (container dropped) |
| Rate limit | reuses `NA_MAX_RPS` (default 2.5 req/s); honours `Retry-After` on 429 |

---

## Error cheat-sheet

| Error | Cause | Fix |
|---|---|---|
| `NA_FEISHU_APP_ID is not set` | no credentials | back to step 3 |
| `code=99991661/99991663/99991664` | token dead / app unpublished | the client refreshes once automatically; if it persists, publish the app version |
| `code=1069902` folder not found | wrong `NA_FEISHU_FOLDER` | check the folder token, or leave it empty |
| `code=1770001` permission denied | scope missing or version unpublished | back to step 2, then release |
| Document exists but is empty | previous run was interrupted | re-run the same command — it tops up |
| Images became link paragraphs | extracted with `--no-assets`, no local copy | re-run extract without `--no-assets`, then publish-feishu |

---

## Lark (international) users

Point the base URL at Lark's Open API domain — everything else is
identical:

```bash
NA_FEISHU_BASE=https://open.larksuite.com
```

Create the app at <https://open.larksuite.com/app>; scope names match.

---

## Security notes

- `NA_FEISHU_APP_SECRET` is the app's password: **never commit it**
  (`.env` is git-ignored), never paste it into issues or screenshots
- grant only the minimum scopes above — resist wildcards like
  `docx:document` apply-all or other high-risk permissions
- documents created by the app belong to the app itself; for team use,
  have an admin approve the version before release
