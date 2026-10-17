# Sample output

This is a **trimmed copy of a real `na demo` run**, committed so you can judge
the output without installing anything.

- Regenerate the full version with `na demo -o examples/demo_output`
  (no credentials required — the demo stage runs on the standard library alone).
- What you are looking at is the **transform + export-md** half of the pipeline
  applied to a synthetic "paid template library" full of the markers the
  cleanser is built to remove.

| File | What it shows |
|---|---|
| [`before-after.md`](before-after.md) | the source page vs. the transformed page, block by block |
| [`reports/transform-report.json`](reports/transform-report.json) | machine-readable count of everything dropped / stripped / retuned |
| [`reports/publish-report.json`](reports/publish-report.json) | the write-back result (pages created, blocks appended, errors) |
| [`markdown/second-brain-os.md`](markdown/second-brain-os.md) | the import-ready Markdown page, as exported |
| [`markdown/INDEX.md`](markdown/INDEX.md) | the bundle index |

The timestamps in the copied files come from the demo run that produced them;
they are not reproducible. The publish report describes a **fresh** run
(`pages_created: 3`); re-running the same command resumes instead, which is
what `pages_reused` counts.
