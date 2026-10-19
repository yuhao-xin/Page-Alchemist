# CLI 参考（CLI Reference）

> 本文档由 `python -m page_alchemist.cli <cmd> --help` 实际输出生成，与实现严格一致。

```text
usage: page-alchemist [-h] [--version] [-v]
                        {extract,transform,publish,publish-feishu,export-md,run,demo,doctor} ...

Extract, cleanse, restructure and re-publish Notion content into your own
knowledge base.

positional arguments:
  {extract,transform,publish,publish-feishu,export-md,run,demo,doctor}
    extract             pull a Notion page tree into IR
    transform           cleanse and restyle the IR
    publish             write the IR into your Notion
    publish-feishu      write the IR into Feishu/Lark Docs
    export-md           render the IR as an import-ready Markdown bundle
    run                 full pipeline: extract -> transform -> publish
    demo                offline demo — no token, no network
    doctor              check environment and configuration

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  -v, --verbose         debug logging

see docs/ for the token tutorial and architecture notes
```

## `extract`

```text
usage: page-alchemist extract [-h] [--engine {api,export,auto}]
                                [--no-assets] [--shallow] [--zip ZIP]
                                [--output OUTPUT] [--env-file ENV_FILE]
                                url

positional arguments:
  url                   Notion page URL or id

options:
  -h, --help            show this help message and exit
  --engine {api,export,auto}
                        api = official integration (default when NOTION_TOKEN
                        is set); export = experimental exportBlock fallback
                        for view-only pages
  --no-assets           do not download images/files (faster, but signed URLs
                        expire)
  --shallow             export engine: root page only, no sub-pages
  --zip ZIP             export engine: parse an already-downloaded export ZIP
                        instead of talking to Notion
  --output, -o OUTPUT   working directory for IR + reports (default: output)
  --env-file ENV_FILE   dotenv file to load (default: .env)
```

## `transform`

```text
usage: page-alchemist transform [-h] [--keep-noise] [--keep-colors]
                                  [--icon-mode {keep,retune,none}]
                                  [--keep-titles] [--keep-h1]
                                  [--keep-duplicates] [--no-archive-card]
                                  [--output OUTPUT] [--env-file ENV_FILE]
                                  input

positional arguments:
  input                 path to structure.json

options:
  -h, --help            show this help message and exit
  --keep-noise          keep table_of_contents / breadcrumb / template blocks
                        (dropped by default)
  --keep-colors         keep original text/background colours
  --icon-mode {keep,retune,none}
                        icon policy (default: retune, or NA_ICON_MODE)
  --keep-titles         do not strip emoji/brand prefixes from titles
  --keep-h1             keep H1 headings (demoted to H2 by default)
  --keep-duplicates     keep exact-duplicate blocks
  --no-archive-card     do not prepend the provenance callout to pages
  --output, -o OUTPUT   working directory for IR + reports (default: output)
  --env-file ENV_FILE   dotenv file to load (default: .env)
```

## `publish`

```text
usage: page-alchemist publish [-h] [--parent PARENT] [--dry-run]
                                [--no-upload] [--output OUTPUT]
                                [--env-file ENV_FILE]
                                input

positional arguments:
  input                path to structure.json or transformed.json

options:
  -h, --help           show this help message and exit
  --parent PARENT      target parent page URL or id in YOUR workspace (or
                       NA_PARENT_PAGE)
  --dry-run            plan everything, make no API calls
  --no-upload          do not upload local assets to Notion
  --output, -o OUTPUT  working directory for IR + reports (default: output)
  --env-file ENV_FILE  dotenv file to load (default: .env)
```

## `publish-feishu`

```text
usage: page-alchemist publish-feishu [-h] [--folder FOLDER] [--dry-run]
                                       [--no-upload] [--output OUTPUT]
                                       [--env-file ENV_FILE]
                                       input

positional arguments:
  input                path to structure.json or transformed.json

options:
  -h, --help           show this help message and exit
  --folder FOLDER      Feishu folder token to create documents in (or
                       NA_FEISHU_FOLDER; omit for the app's root)
  --dry-run            plan everything, make no API calls
  --no-upload          do not upload local images to Feishu
  --output, -o OUTPUT  working directory for IR + reports (default: output)
  --env-file ENV_FILE  dotenv file to load (default: .env)
```

## `export-md`

```text
usage: page-alchemist export-md [-h] [--no-assets] [--output OUTPUT]
                                  [--env-file ENV_FILE]
                                  input

positional arguments:
  input                path to structure.json or transformed.json

options:
  -h, --help           show this help message and exit
  --no-assets          do not copy local assets into the bundle
  --output, -o OUTPUT  working directory for IR + reports (default: output)
  --env-file ENV_FILE  dotenv file to load (default: .env)
```

## `run`

```text
usage: page-alchemist run [-h] [--engine {api,export,auto}] [--no-assets]
                            [--shallow] [--zip ZIP] [--keep-noise]
                            [--keep-colors] [--icon-mode {keep,retune,none}]
                            [--keep-titles] [--keep-h1] [--keep-duplicates]
                            [--no-archive-card] [--parent PARENT] [--dry-run]
                            [--no-upload] [--from FROM_FILE] [--md-only]
                            [--output OUTPUT] [--env-file ENV_FILE]
                            [url]

positional arguments:
  url                   Notion page URL or id (not needed with --from)

options:
  -h, --help            show this help message and exit
  --engine {api,export,auto}
                        api = official integration (default when NOTION_TOKEN
                        is set); export = experimental exportBlock fallback
                        for view-only pages
  --no-assets           do not download images/files (faster, but signed URLs
                        expire)
  --shallow             export engine: root page only, no sub-pages
  --zip ZIP             export engine: parse an already-downloaded export ZIP
                        instead of talking to Notion
  --keep-noise          keep table_of_contents / breadcrumb / template blocks
                        (dropped by default)
  --keep-colors         keep original text/background colours
  --icon-mode {keep,retune,none}
                        icon policy (default: retune, or NA_ICON_MODE)
  --keep-titles         do not strip emoji/brand prefixes from titles
  --keep-h1             keep H1 headings (demoted to H2 by default)
  --keep-duplicates     keep exact-duplicate blocks
  --no-archive-card     do not prepend the provenance callout to pages
  --parent PARENT       target parent page URL or id in YOUR workspace (or
                        NA_PARENT_PAGE)
  --dry-run             plan everything, make no API calls
  --no-upload           do not upload local assets to Notion
  --from FROM_FILE      start from an existing IR json instead of extracting
                        (skips stage 1)
  --md-only             publish stage becomes export-md (no Notion writes)
  --output, -o OUTPUT   working directory for IR + reports (default: output)
  --env-file ENV_FILE   dotenv file to load (default: .env)
```

## `demo`

```text
usage: page-alchemist demo [-h] [--output OUTPUT] [--env-file ENV_FILE]

options:
  -h, --help           show this help message and exit
  --output, -o OUTPUT  working directory for IR + reports (default: output)
  --env-file ENV_FILE  dotenv file to load (default: .env)
```

## `doctor`

```text
usage: page-alchemist doctor [-h] [--env-file ENV_FILE]

options:
  -h, --help           show this help message and exit
  --env-file ENV_FILE  dotenv file to load (default: .env)
```

