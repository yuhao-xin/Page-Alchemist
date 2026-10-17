# Examples

This directory holds **generated** output and is intentionally not tracked
in git (see `.gitignore`). Recreate it any time with:

```bash
na demo                       # installed: writes examples/demo_output/
bash scripts/na.sh demo       # from a checkout, no install needed
```

What you get in `examples/demo_output/`:

| File | Stage | Contents |
|---|---|---|
| `structure.json` | Extract | canonical IR of the mock library |
| `extract-report.json` | Extract | engine, page/block counts |
| `transformed.json` | Transform | IR after cleansing / icon retune / relayout |
| `transform-report.json` | Transform | what was dropped, stripped, retuned |
| `publish-report.json` | Publish | dry-run plan (pages, blocks, databases, rows) |
| `markdown-report.json` | Export | bundle statistics |
| `bundle/` | Export | import-ready Markdown + assets + `INDEX.md` |
| `assets/` | Extract | downloaded mock image |
