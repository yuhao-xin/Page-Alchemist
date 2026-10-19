# Notion credential setup

> Audience: someone who has never configured the Notion API. About 5 minutes,
> no code required.
> The two engines need different credentials: the **official API engine**
> (recommended, stable) uses an *integration token*; the **export fallback
> engine** (experimental) uses a *token_v2 cookie*. If you only want the demo
> or a Markdown export, you need neither.

---

## Contents

1. [Engine A — official API (recommended)](#engine-a--official-api-recommended)
2. [Engine B — export fallback (experimental, view-only pages)](#engine-b--export-fallback-experimental-view-only-pages)
3. [Write `.env`](#write-env)
4. [Verify](#verify)
5. [Error cheat-sheet](#error-cheat-sheet)
6. [Credentials in Docker / GitHub Actions](#credentials-in-docker--github-actions)
7. [Security notes](#security-notes)

---

## Engine A — official API (recommended)

You need access to **two** pages: ① the **source page** you want to extract,
and ② a **parent page** in your own workspace that will receive the result.
Both must be shared with the integration.

### Step 1 — create an internal integration

1. Sign in to Notion **with the account that owns the target workspace**, and
   open <https://www.notion.so/my-integrations>
2. Click **+ New integration**
3. Fill in:
   - **Name** — something recognisable, e.g. `Page Alchemist` (this name
     shows up in the page's *Connections* list)
   - **Associated workspace** — pick the target workspace (an integration is
     bound to one workspace; a different workspace needs a new integration)
   - **Logo** — skip it
4. Click **Submit**

> ⚠️ Only a **Workspace Owner** can create integrations. Members and Guests
> cannot see that page — have the owner create it, or elevate your account.

### Step 2 — copy the Integration Secret

On the integration's config page, find **Internal Integration Secret**:

- New integrations get a long string starting with `ntn_`; integrations
  created before late 2024 start with `secret_`. **The API accepts both** —
  mixing them is fine.
- Click **Show** and copy the full token.
- The token **does not expire on its own**. If you suspect a leak, come back
  to this page and click **Refresh** to invalidate the old one.

### Step 3 — configure Capabilities

In the **Capabilities** section of the same page, tick **all three**:

| Capability | Used for |
|---|---|
| ☑ **Read content** | the extract stage reads the source page tree |
| ☑ **Insert content** | the publish stage creates pages / appends blocks |
| ☑ **Update content** | icons, covers, and resuming an interrupted publish |

Leave *User capabilities* alone. Changing capabilities later does **not**
require regenerating the token.

### Step 4 — share the pages with the integration (the step everyone misses)

**Creating an integration is not the same as granting access.** If you skip
this, the API returns `404 Could not find object` — note **404, not 403**;
Notion does this deliberately so an unauthorised integration cannot probe
whether a page exists.

1. Open the **source page** in Notion
2. Click the **···** menu in the top-right
3. Find **Connections**
4. Search for and select the integration you just created
5. Repeat 1–4 for the **parent page** in your own workspace

Sharing is **inherited downward**: once you share a top-level page, every
child page and child database under it is reachable. So the cheapest setup is
to share only the root of the source library plus your target parent page.

### Step 5 — write it into `.env`

See [Write `.env`](#write-env) below — you only need `NOTION_TOKEN` and
`NA_PARENT_PAGE`.

---

## Engine B — export fallback (experimental, view-only pages)

When you have **view-only** access to a page (say, a guest link to someone
else's paid template library) and cannot share it with an integration, the
official API cannot reach it. This tool offers an experimental fallback: it
calls Notion's web export task (`exportBlock`), which is equivalent to
clicking *Export → Markdown & CSV* in the browser — just automated.

It needs `token_v2`, a cookie from your **logged-in notion.so browser
session**:

1. Sign in to <https://www.notion.so> in Chrome/Edge
2. Press `F12` → **Application** tab
3. In the left pane, **Cookies → `https://www.notion.so`**
4. Find the entry named **`token_v2`** and copy its Value (a long string)
5. Put it in `.env` as `NOTION_TOKEN_V2=`

Notes:

- `token_v2` **is your logged-in session** — anyone holding it is logged in
  as you. It dies when you sign out or change your password. Keep it in your
  local `.env` only. **Never** send it to anyone, never commit it.
- The export engine gets a ZIP (Markdown + CSV + images) and parses it into
  exactly the same IR as the official engine; transform and publish behave
  identically downstream.
- It depends on a Notion-internal web endpoint that may change at any time —
  hence **experimental**, with no long-term availability guarantee. If the
  official API can reach the page, use it instead.

---

## Write `.env`

From the project root:

```bash
cp .env.example .env
```

Then edit `.env`:

```ini
# —— Engine A: official API (recommended) ——
NOTION_TOKEN=ntn_your_integration_secret
NA_PARENT_PAGE=https://www.notion.so/your-parent-page

# —— Engine B: export fallback (experimental, optional) ——
# NOTION_TOKEN_V2=your_token_v2_cookie

# —— Optional, all have defaults ——
# NA_ICON_MODE=retune          # keep | retune | none
# NA_MAX_RPS=2.5               # write rate cap; do not raise
# NA_STATE_DIR=.               # where .na_state.json lives
# NA_OUTPUT_DIR=output
# NOTION_FILE_TOKEN=           # spare file-upload token (usually unused)
```

`NA_PARENT_PAGE` accepts a full URL or just the page ID (32 hex characters,
hyphens optional).

---

## Verify

```bash
# 1. the tool's own check: token shape, writable dirs, dependencies
na doctor

# 2. native verification (optional): ask Notion which databases this
#    integration can see
curl -X POST "https://api.notion.com/v1/search" \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"filter": {"property": "object", "value": "database"}}'
```

If your pages/databases show up in `results`, you are set. An empty
`results` means the token is valid but no page has been shared yet — go back
to step 4.

---

## Error cheat-sheet

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` | token mistyped / invalidated by Refresh | re-copy the full `ntn_...` string |
| `404 Could not find object` | page not shared with the integration (**most common**) | page `···` → Connections → pick the integration |
| `search` returns an empty list | same as above — nothing shared | same as above |
| `429 Too Many Requests` | above ~3 req/s | the tool rate-limits and retries internally; if you run other scripts, lower `NA_MAX_RPS` |
| `validation_error` | request body does not match the schema | usually caused by upgrading to a newer API version that renamed fields; this tool pins `2022-06-28` — leave it |
| `503` + `retry_guidance: do_not_retry` | the write actually **succeeded**; Notion refuses to let you replay it | the tool records it in the state file; re-running the same command resumes instead of duplicating |
| `my-integrations` page not visible | your account is not a Workspace Owner | have the owner create the integration |
| images extracted as dead links | Notion file URLs expire after ~1 hour | already downloaded to `output/assets/` at extract time; don't pass `--no-assets` |

---

## Credentials in Docker / GitHub Actions

**Docker** (`docker-compose.yml` has the injection points ready):

```bash
# run from the directory containing .env; compose picks it up
NOTION_TOKEN=ntn_xxx NA_PARENT_PAGE=https://... \
  docker compose run --rm alchemist run "<source-page-url>"
```

**GitHub Actions** (for scheduled re-publishing, etc.): go to the repo's
**Settings → Secrets and variables → Actions → New repository secret** and
add `NOTION_TOKEN` and `NA_PARENT_PAGE`, then reference them in a workflow:

```yaml
- run: page-alchemist run "$SOURCE_URL" --parent "$NA_PARENT_PAGE"
  env:
    NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
    NA_PARENT_PAGE: ${{ secrets.NA_PARENT_PAGE }}
```

---

## Security notes

- `.env` is already in `.gitignore`; **double-check** that you never
  `git add` it.
- Keep tokens on your own machine. Never paste a full token into a chat
  window, an issue, or a screenshot.
- Create a separate integration per project rather than reusing one across
  your whole account — the page *Connections* list is your best audit log.
- Extract only content **you are authorised to access**, and respect the
  source's licence and Notion's Terms of Use. This tool automates what you
  could do by hand; it bypasses no permission.

---

*The authoritative definition of every credential field lives in
[`../src/page_alchemist/config.py`](../src/page_alchemist/config.py).
When in doubt, run `na doctor` first.*
