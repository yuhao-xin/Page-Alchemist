"""Command-line interface — the single entry point for the whole pipeline.

Subcommands
-----------
``extract``     pull a Notion page tree into the canonical IR (``structure.json``)
``transform``   cleanse / restyle / re-layout the IR (``transformed.json``)
``publish``     write the IR back into your own Notion workspace
``export-md``   render the IR as an import-ready Markdown bundle
``run``         the full pipeline: extract -> transform -> publish (or --md-only)
``demo``        offline demo: no token, no network, full artifact set
``doctor``      environment + configuration health check

Design notes
------------
* Every stage reads/writes plain JSON IR, so stages can be run separately,
  re-run, or resumed — nothing is locked to a single process lifetime.
* ``--help`` and ``doctor`` must work without ``requests`` installed: the
  network modules import lazily inside their engines.
* Exit codes: ``0`` success, ``1`` runtime failure, ``2`` configuration
  problem (fixable by the user, see ``doctor``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .config import Settings
from .models import Document
from .util import get_logger, setup_logging

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2

STRUCTURE = "structure.json"
TRANSFORMED = "transformed.json"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)  # atomic on the same filesystem


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_document(path: Path) -> Document:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    return Document.from_dict(_read_json(path))


def _banner(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def _fail(msg: str, code: int = EXIT_ERROR) -> "SystemExit":
    print(f"error: {msg}", file=sys.stderr)
    return SystemExit(code)


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
def cmd_extract(args: argparse.Namespace, settings: Settings) -> int:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    asset_dir = out / "assets"

    engine = args.engine
    if engine == "auto":
        engine = "api" if settings.notion_token else (
            "export" if settings.notion_token_v2 else "api")
        get_logger().info("auto engine -> %s", engine)

    if engine == "api":
        problems = settings.problems(need_token=True)
        if problems:
            for p in problems:
                print(f"error: {p}", file=sys.stderr)
            return EXIT_CONFIG
        from .notion_api import extract_via_api
        doc = extract_via_api(args.url, settings,
                              download_assets=not args.no_assets,
                              asset_dir=asset_dir)
    elif engine == "export":
        problems = settings.problems_unofficial()
        if problems:
            for p in problems:
                print(f"error: {p}", file=sys.stderr)
            return EXIT_CONFIG
        from .notion_unofficial import extract_via_export
        doc = extract_via_export(
            args.url, settings, recursive=not args.shallow,
            workdir=out / "_export", zip_path=args.zip)
    else:  # pragma: no cover - argparse choices guard this
        return _fail(f"unknown engine {engine!r}", EXIT_CONFIG).code

    structure_path = out / STRUCTURE
    _write_json(structure_path, doc.to_dict())
    _write_json(out / "extract-report.json", {
        "engine": doc.engine,
        "source_url": doc.source_url,
        "pages": sum(1 for _ in doc.iter_pages()),
        "blocks": doc.count_blocks(),
        "stats": doc.stats,
        "structure": str(structure_path),
    })

    _banner("extract done")
    print(f"engine      : {doc.engine}")
    print(f"pages       : {sum(1 for _ in doc.iter_pages())}")
    print(f"blocks      : {doc.count_blocks()}")
    print(f"structure   : {structure_path}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# transform
# --------------------------------------------------------------------------- #
def cmd_transform(args: argparse.Namespace, settings: Settings) -> int:
    from .transform import TransformOptions, transform_document

    src = Path(args.input)
    doc = _load_document(src)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    options = TransformOptions(
        drop_noise=not args.keep_noise,
        strip_colors=not args.keep_colors,
        icon_mode=args.icon_mode or settings.icon_mode,
        normalize_titles=not args.keep_titles,
        demote_h1=not args.keep_h1,
        dedupe=not args.keep_duplicates,
        add_archive_card=not args.no_archive_card,
    )
    problems = options.problems()
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return EXIT_CONFIG

    before = doc.count_blocks()
    report = transform_document(doc, options)

    transformed_path = out / TRANSFORMED
    _write_json(transformed_path, doc.to_dict())
    _write_json(out / "transform-report.json", report.to_dict())

    _banner("transform done")
    print(report.summary())
    print(f"blocks      : {before} -> {doc.count_blocks()}")
    print(f"transformed : {transformed_path}")
    for note in report.notes:
        print(f"note        : {note}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# publish
# --------------------------------------------------------------------------- #
def cmd_publish(args: argparse.Namespace, settings: Settings) -> int:
    from .publish import publish_document

    src = Path(args.input)
    doc = _load_document(src)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    parent = (args.parent or settings.parent_page or "").strip()
    if not parent:
        print("error: no parent page given. Use --parent <notion-url-or-id> "
              "or set NA_PARENT_PAGE (see docs/notion-token-setup.md).",
              file=sys.stderr)
        return EXIT_CONFIG
    # feed the CLI flag back into settings so downstream validation sees it
    settings.parent_page = parent
    if args.dry_run:
        # dry-run validates config but must not require a token
        settings = Settings(**{**settings.__dict__, "notion_token":
                               settings.notion_token or "dry-run"})

    try:
        report = publish_document(
            doc, settings, parent_page_id=parent,
            dry_run=args.dry_run, upload_files=not args.no_upload)
    except ValueError as exc:  # configuration problems surface here
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("\ninterrupted — progress saved to .na_state.json, re-run to resume",
              file=sys.stderr)
        return EXIT_ERROR

    _write_json(out / "publish-report.json", report.to_dict())
    _banner("publish done (dry-run)" if args.dry_run else "publish done")
    print(report.summary())
    for action in report.actions:
        print(f"  {action.get('op'):<16} {action.get('page') or action.get('title', '')}")
    for err in report.errors:
        print(f"  ERROR {err}", file=sys.stderr)
    if args.dry_run:
        print("\nthis was a dry run — no API calls were made. "
              "Drop --dry-run to publish for real.")
    return EXIT_ERROR if report.errors else EXIT_OK


# --------------------------------------------------------------------------- #
# export-md
# --------------------------------------------------------------------------- #
def cmd_export_md(args: argparse.Namespace, settings: Settings) -> int:
    from .export_md import export_markdown

    doc = _load_document(Path(args.input))
    out = Path(args.output) / "bundle"
    report = export_markdown(doc, out, copy_assets=not args.no_assets)
    _write_json(Path(args.output) / "markdown-report.json", report.to_dict())

    _banner("markdown export done")
    print(report.summary())
    print(f"bundle      : {out}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# run (full pipeline)
# --------------------------------------------------------------------------- #
def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    if not args.from_file and not args.url:
        print("error: run needs either a Notion url or --from <structure.json>",
              file=sys.stderr)
        return EXIT_CONFIG
    # 1. extract (reuse an existing structure.json when --from is given)
    if args.from_file:
        doc = _load_document(Path(args.from_file))
        print(f"reusing existing IR: {args.from_file} "
              f"({sum(1 for _ in doc.iter_pages())} pages)")
    else:
        code = cmd_extract(args, settings)
        if code != EXIT_OK:
            return code
        doc = _load_document(Path(args.output) / STRUCTURE)

    # 2. transform — with --from the IR lives at the source path
    ir_path = Path(args.from_file) if args.from_file else Path(args.output) / STRUCTURE
    targs = argparse.Namespace(**{**vars(args), "input": str(ir_path)})
    code = cmd_transform(targs, settings)
    if code != EXIT_OK:
        return code
    doc = _load_document(Path(args.output) / TRANSFORMED)

    # 3. publish or export-md
    if args.md_only:
        margs = argparse.Namespace(**{**vars(args),
                                      "input": str(Path(args.output) / TRANSFORMED)})
        return cmd_export_md(margs, settings)
    pargs = argparse.Namespace(**{**vars(args),
                                  "input": str(Path(args.output) / TRANSFORMED)})
    return cmd_publish(pargs, settings)


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #
def cmd_demo(args: argparse.Namespace, settings: Settings) -> int:
    from .demo import run_demo

    out = Path(args.output)
    summary = run_demo(out)
    _banner("demo done")
    for key in ("pages", "blocks", "transform", "publish_plan", "markdown"):
        if key in summary:
            print(f"{key:<13}: {summary[key]}")
    print(f"output       : {out.resolve()}")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    import platform

    _banner("notion-alchemist doctor")
    print(f"version      : {__version__}")
    print(f"python       : {platform.python_version()}")

    problems: List[str] = []

    # requests — only needed for network engines
    try:
        import requests  # noqa: F401
        print("requests     : installed")
    except ImportError:
        print("requests     : MISSING (needed by extract/publish; "
              "demo, transform and export-md work without it)")
        problems.append("pip install requests")

    print(f"NOTION_TOKEN : {settings.masked_token()}")
    if not settings.notion_token:
        problems.append("NOTION_TOKEN not set — see docs/notion-token-setup.md")
    print(f"TOKEN_V2     : {'set' if settings.notion_token_v2 else '(not set)'}")
    print(f"FILE_TOKEN   : {'set' if settings.file_token else '(not set)'}")
    print(f"parent page  : {settings.parent_page or '(not set)'}")
    print(f"icon mode    : {settings.icon_mode}")
    print(f"max rps      : {settings.max_rps}")
    print(f"state dir    : {settings.state_dir}")
    print(f"output dir   : {settings.output_dir}")

    for name in ("state_dir", "output_dir"):
        target = Path(getattr(settings, name))
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".na-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            print(f"{name:<13}: writable")
        except OSError as exc:
            print(f"{name:<13}: NOT writable ({exc})")
            problems.append(f"{name} {target} is not writable")

    problems += settings.problems()
    if problems:
        print("\nfixable problems:")
        for p in problems:
            print(f"  - {p}")
        return EXIT_CONFIG
    print("\nall checks passed — ready to extract, transform and publish.")
    return EXIT_OK


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notion-alchemist",
        description="Extract, cleanse, restructure and re-publish Notion "
                    "content into your own knowledge base.",
        epilog="see docs/ for the token tutorial and architecture notes",
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp, *, out=True):
        if out:
            sp.add_argument("--output", "-o", default="output",
                            help="working directory for IR + reports "
                                 "(default: output)")
        sp.add_argument("--env-file", default=".env",
                        help="dotenv file to load (default: .env)")

    def add_extract_args(sp, *, url_optional: bool = False):
        if url_optional:
            sp.add_argument("url", nargs="?", default=None,
                            help="Notion page URL or id (not needed with --from)")
        else:
            sp.add_argument("url", help="Notion page URL or id")
        sp.add_argument("--engine", choices=["api", "export", "auto"],
                        default="auto",
                        help="api = official integration (default when "
                             "NOTION_TOKEN is set); export = experimental "
                             "exportBlock fallback for view-only pages")
        sp.add_argument("--no-assets", action="store_true",
                        help="do not download images/files (faster, but "
                             "signed URLs expire)")
        sp.add_argument("--shallow", action="store_true",
                        help="export engine: root page only, no sub-pages")
        sp.add_argument("--zip", default=None,
                        help="export engine: parse an already-downloaded "
                             "export ZIP instead of talking to Notion")

    def add_transform_args(sp):
        sp.add_argument("--keep-noise", action="store_true",
                        help="keep table_of_contents / breadcrumb / template "
                             "blocks (dropped by default)")
        sp.add_argument("--keep-colors", action="store_true",
                        help="keep original text/background colours")
        sp.add_argument("--icon-mode", choices=["keep", "retune", "none"],
                        default=None, help="icon policy (default: retune, "
                                           "or NA_ICON_MODE)")
        sp.add_argument("--keep-titles", action="store_true",
                        help="do not strip emoji/brand prefixes from titles")
        sp.add_argument("--keep-h1", action="store_true",
                        help="keep H1 headings (demoted to H2 by default)")
        sp.add_argument("--keep-duplicates", action="store_true",
                        help="keep exact-duplicate blocks")
        sp.add_argument("--no-archive-card", action="store_true",
                        help="do not prepend the provenance callout to pages")

    def add_publish_args(sp):
        sp.add_argument("--parent", default=None,
                        help="target parent page URL or id in YOUR workspace "
                             "(or NA_PARENT_PAGE)")
        sp.add_argument("--dry-run", action="store_true",
                        help="plan everything, make no API calls")
        sp.add_argument("--no-upload", action="store_true",
                        help="do not upload local assets to Notion")

    # extract
    sp = sub.add_parser("extract", help="pull a Notion page tree into IR")
    add_extract_args(sp)
    add_common(sp)
    sp.set_defaults(func=cmd_extract)

    # transform
    sp = sub.add_parser("transform", help="cleanse and restyle the IR")
    sp.add_argument("input", help=f"path to {STRUCTURE}")
    add_transform_args(sp)
    add_common(sp)
    sp.set_defaults(func=cmd_transform)

    # publish
    sp = sub.add_parser("publish", help="write the IR into your Notion")
    sp.add_argument("input", help=f"path to {STRUCTURE} or {TRANSFORMED}")
    add_publish_args(sp)
    add_common(sp)
    sp.set_defaults(func=cmd_publish)

    # export-md
    sp = sub.add_parser("export-md",
                        help="render the IR as an import-ready Markdown bundle")
    sp.add_argument("input", help=f"path to {STRUCTURE} or {TRANSFORMED}")
    sp.add_argument("--no-assets", action="store_true",
                    help="do not copy local assets into the bundle")
    add_common(sp)
    sp.set_defaults(func=cmd_export_md)

    # run
    sp = sub.add_parser("run", help="full pipeline: extract -> transform -> "
                                    "publish")
    add_extract_args(sp, url_optional=True)
    add_transform_args(sp)
    add_publish_args(sp)
    sp.add_argument("--from", dest="from_file", default=None,
                    help="start from an existing IR json instead of "
                         "extracting (skips stage 1)")
    sp.add_argument("--md-only", action="store_true",
                    help="publish stage becomes export-md (no Notion writes)")
    add_common(sp)
    sp.set_defaults(func=cmd_run)

    # demo
    sp = sub.add_parser("demo", help="offline demo — no token, no network")
    sp.add_argument("--output", "-o", default="examples/demo_output",
                    help="working directory (default: examples/demo_output)")
    sp.add_argument("--env-file", default=".env",
                    help="dotenv file to load (default: .env)")
    sp.set_defaults(func=cmd_demo)

    # doctor
    sp = sub.add_parser("doctor", help="check environment and configuration")
    add_common(sp, out=False)
    sp.set_defaults(func=cmd_doctor)

    return p


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging("DEBUG" if args.verbose else "INFO")
    settings = Settings.load(args.env_file)
    # CLI flags win over env for the paths that matter most
    if getattr(args, "output", None):
        settings.output_dir = args.output
        # keep the resumable state next to the working directory unless the
        # user pinned it explicitly with NA_STATE_DIR
        if not os.environ.get("NA_STATE_DIR"):
            settings.state_dir = args.output

    try:
        return args.func(args, settings)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return EXIT_OK
        if isinstance(code, int):
            return code
        print(f"error: {code}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # surface a clean one-line error, traceback with -v
        if args.verbose:
            raise
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("hint: re-run with -v for the full traceback", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
