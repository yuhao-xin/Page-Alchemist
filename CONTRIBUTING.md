# Contributing to Page Alchemist

Thanks for your interest in improving Page Alchemist! This document describes
how to set up a development environment and the conventions we follow.

## Development setup

```bash
git clone https://github.com/yuhao-xin/page-alchemist.git
cd page-alchemist
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Common commands

| Command | Purpose |
|---|---|
| `make test` / `pytest` | Run the test suite (no network required) |
| `make lint` / `ruff check src tests` | Lint |
| `make demo` | Run the full pipeline on built-in mock data |
| `page-alchemist doctor` | Validate your local configuration |

## Conventions

- **Python ≥ 3.9**, standard library plus `requests` only for runtime deps.
- Keep the official Notion API engine stable and well-tested; anything touching
  the unofficial engine must be clearly marked experimental and must fail soft.
- Every transform rule is data-driven and must be unit-testable without network.
- Public API changes need a `CHANGELOG.md` entry.
- Run `ruff` before opening a PR.

## Pull requests

1. Fork and create a branch: `feat/short-description`.
2. Add/adjust tests; keep `pytest` green.
3. Update docs (`README.md`, `README.zh-CN.md`, `docs/`) when behaviour changes.
4. Open the PR and fill in the template.

## Reporting bugs

Please use the bug report template and include:

- the exact Notion URL *shape* you used (redact private IDs if needed),
- the engine (`--backend api|unofficial`),
- the command line, and the sanitized log output.

## Security

Never paste real `NOTION_TOKEN` / `NOTION_TOKEN_V2` values into issues.
See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
