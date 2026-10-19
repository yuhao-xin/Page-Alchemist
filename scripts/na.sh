#!/usr/bin/env bash
# page-alchemist wrapper — run the CLI straight from a git checkout,
# no installation required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PY="${PAGE_ALCHEMIST_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "error: no python3 found. Set PAGE_ALCHEMIST_PYTHON." >&2
  exit 1
fi

cd "$HERE"
# relative PYTHONPATH entry: works regardless of how the shell spells $HERE
# (Git Bash's /d/... and cmd's D:\... both break absolute PYTHONPATH values).
# Windows python joins PYTHONPATH with ';' — mixing separators corrupts the
# whole variable, so pick the right one for the platform we are actually on.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) SEP=";" ;;
  *) SEP=":" ;;
esac
PYTHONPATH="src${PYTHONPATH:+$SEP$PYTHONPATH}" exec "$PY" -m page_alchemist.cli "$@"
