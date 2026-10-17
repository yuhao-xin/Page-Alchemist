"""Tests for the SkillHub pre-flight checker itself.

The checker is the gate between "we think we are compliant" and "the platform
agrees", so its *detection* logic is worth locking down: a broken checker is
worse than no checker, because it reports green while things are red.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import skillhub_preflight as preflight  # noqa: E402

# A slug with no generic word in it, so the clean-case fixtures stay clean.
PKG = "notion-tidier"


def _write_skill(root: Path, *, name=PKG, description=None, body=None):
    fm = [
        "---",
        f"name: {name}",
        "description: >-",
    ]
    desc = description if description is not None else (
        'Do a thing with a Notion page. Use when the user says "extract this '
        'Notion page", "clone this template", "Notion \u63d0\u53d6", '
        '"Notion \u5bfc\u51fa Markdown".'
    )
    for line in desc.split("\n"):
        fm.append(f"  {line}")
    fm += [
        "license: MIT",
        "compatibility: Requires Python >= 3.9",
        "---",
        "",
    ]
    # A body that is honest about scope: the boundary markers the checker
    # looks for, plus the reference file it expects to exist.
    if body is None:
        body = (
            "# Tidier\n\n"
            "Only extract content you are authorised to access.\n"
            "The unofficial engine is experimental and not guaranteed.\n"
            "Feishu extraction is a separate project.\n"
        )
        (root / "references").mkdir(exist_ok=True)
        (root / "references" / "cli-reference.md").write_text(
            "# CLI reference\n", encoding="utf-8")
    fm.append(body)
    (root / "SKILL.md").write_text("\n".join(fm), encoding="utf-8")


def _pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / PKG
    pkg.mkdir()
    return pkg


# ---------------------------------------------------------------- clean case

def test_clean_package_passes(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg)
    assert preflight.check(pkg) == 0


def test_real_repository_passes():
    """The shipped repo must score exit 0 — this is the regression guard."""
    assert preflight.check(ROOT) == 0


# ------------------------------------------------------------- hard failures

def test_missing_skill_md_returns_2(tmp_path):
    assert preflight.check(tmp_path) == 2


def test_name_directory_mismatch_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, name="other-name")
    assert preflight.check(pkg) == 2


def test_generic_slug_words_are_errors(tmp_path):
    # loop rather than parametrize: the zero-dependency runner does not
    # implement pytest.mark.parametrize, and this suite must stay dual-track.
    for slug in ["tool", "my-helper", "notion-utils", "skill-kit", "utils"]:
        pkg = tmp_path / slug
        pkg.mkdir()
        _write_skill(pkg, name=slug)
        assert preflight.check(pkg) == 2, slug


def test_hardcoded_token_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, body="# T\n\nExample token: ntn_" + "a" * 40 + "\n")
    assert preflight.check(pkg) == 2


def test_phone_number_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, body="# T\n\nReach me at 13800138000 anytime.\n")
    assert preflight.check(pkg) == 2


def test_missing_required_frontmatter_field_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    (pkg / "SKILL.md").write_text(
        "---\nname: notion-tidier\n---\n\n# T\n", encoding="utf-8")
    assert preflight.check(pkg) == 2


def test_no_frontmatter_returns_2(tmp_path):
    pkg = _pkg(tmp_path)
    (pkg / "SKILL.md").write_text("# just a title\n", encoding="utf-8")
    assert preflight.check(pkg) == 2


# ------------------------------------------------------------- description

def test_english_only_description_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, description=(
        'Do a thing. Use when the user says "extract this Notion page", '
        '"clone this template", "export markdown".'
    ))
    assert preflight.check(pkg) == 2


def test_too_few_trigger_phrases_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, description=(
        'Extract Notion \u9875\u9762\u3002 Use for "extract this page" only.'
    ))
    assert preflight.check(pkg) == 2


def test_overly_short_description_is_an_error(tmp_path):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, description="Notion tool.")
    assert preflight.check(pkg) == 2


# ------------------------------------------------------------------ warnings

def test_absolute_path_is_a_warning_not_an_error(tmp_path, capsys):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, body="# T\n\nSee C:\\\\Users\\\\someone\\\\notes.md for details.\n")
    code = preflight.check(pkg)
    out = capsys.readouterr().out
    assert code == 1
    assert "absolute path" in out


def test_missing_referenced_doc_is_a_warning(tmp_path, capsys):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, body="# T\n\nSee `docs/does-not-exist.md` for details.\n")
    assert preflight.check(pkg) == 1
    assert "does-not-exist.md" in capsys.readouterr().out


def test_vague_boundaries_are_a_warning(tmp_path, capsys):
    pkg = _pkg(tmp_path)
    _write_skill(pkg, body="# T\n\nIt just works, always, for everything.\n")
    assert preflight.check(pkg) == 1
    assert "boundary" in capsys.readouterr().out


# ------------------------------------------------------------------ parsing

def test_folded_block_description_is_joined():
    fm, body = preflight._read_frontmatter(
        "---\nname: x\ndescription: >-\n  first line\n  second line\n"
        "license: MIT\n---\n\nbody\n")
    assert fm is not None
    data = preflight._parse_simple_yaml(fm)
    assert data["description"] == "first line second line"
    assert "body" in body


def test_frontmatter_absent():
    fm, body = preflight._read_frontmatter("# no frontmatter\n")
    assert fm is None
    assert "no frontmatter" in body


def test_plain_scalar_description():
    data = preflight._parse_simple_yaml(
        "name: notion-tidier\ndescription: A single line.\n")
    assert data == {"name": "notion-tidier", "description": "A single line."}


def test_test_fixtures_are_excluded_from_the_scan(tmp_path):
    """A checker that scans its own tests flags its own fake tokens.

    ``tests/`` and ``fixtures/`` are fixture space, not shipped payload, so a
    deliberately-fake credential living there must not fail the package.
    """
    pkg = _pkg(tmp_path)
    _write_skill(pkg)
    (pkg / "tests").mkdir()
    (pkg / "tests" / "test_fixture.py").write_text(
        "TOKEN = 'ntn_" + "b" * 40 + "'\nPHONE = '13900139000'\n",
        encoding="utf-8")
    assert preflight.check(pkg) == 0
