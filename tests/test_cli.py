"""CLI: argument wiring, exit codes, and the offline stages end to end."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from page_alchemist import cli
from page_alchemist.config import Settings


def run_cli(argv):
    """Run main() with a controlled env; return the exit code."""
    return cli.main(argv)


class TestHelpAndVersion:
    def test_help_lists_subcommands(self, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for cmd in ("extract", "transform", "publish", "export-md", "run",
                    "demo", "doctor"):
            assert cmd in out

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0
        assert "0.1.0" in capsys.readouterr().out


class TestDoctor:
    def test_reports_config_problems(self, capsys):
        code = run_cli(["doctor"])
        out = capsys.readouterr().out
        assert code in (0, 2)
        assert "page-alchemist doctor" in out
        assert "python" in out


class TestDemo:
    def test_full_offline_pipeline(self, tmp_path, capsys):
        out = tmp_path / "demo"
        code = run_cli(["demo", "-o", str(out)])
        assert code == 0
        summary = json.loads((out / "demo-summary.json").read_text("utf-8"))
        assert summary["pages"] == 3
        # all stage artefacts exist
        for name in ("structure.json", "transformed.json",
                     "transform-report.json", "publish-report.json",
                     "markdown-report.json"):
            assert (out / name).exists(), name
        assert (out / "bundle" / "INDEX.md").exists()

    def test_bundle_contents(self, tmp_path):
        out = tmp_path / "demo"
        run_cli(["demo", "-o", str(out)])
        md = (out / "bundle" / "second-brain-os" / "second-brain-os.md")
        text = md.read_text(encoding="utf-8")
        assert "empty the inbox" in text
        assert "assets/diagram.png" in text


class TestTransformCommand:
    def test_structure_to_transformed(self, tmp_path):
        demo = tmp_path / "demo"
        run_cli(["demo", "-o", str(demo)])
        out = tmp_path / "work"
        code = run_cli(["transform", str(demo / "structure.json"),
                        "-o", str(out)])
        assert code == 0
        assert (out / "transformed.json").exists()
        assert (out / "transform-report.json").exists()

    def test_missing_input_is_clean_error(self, tmp_path, capsys):
        code = run_cli(["transform", str(tmp_path / "nope.json"),
                        "-o", str(tmp_path / "work")])
        assert code == 1
        assert "not found" in capsys.readouterr().err


class TestPublishCommand:
    def test_dry_run_without_token(self, tmp_path, capsys):
        demo = tmp_path / "demo"
        run_cli(["demo", "-o", str(demo)])
        out = tmp_path / "work"
        code = run_cli([
            "publish", str(demo / "transformed.json"),
            "--parent", "https://www.notion.so/target-"
                        "0123456789abcdef0123456789abcdef",
            "--dry-run", "-o", str(out)])
        assert code == 0
        report = json.loads((out / "publish-report.json").read_text("utf-8"))
        assert report["pages_created"] == 3
        assert "dry run" in capsys.readouterr().out

    def test_missing_parent_is_config_error(self, tmp_path, capsys, monkeypatch):
        demo = tmp_path / "demo"
        run_cli(["demo", "-o", str(demo)])
        monkeypatch.delenv("NA_PARENT_PAGE", raising=False)
        code = run_cli(["publish", str(demo / "transformed.json"),
                        "--dry-run", "-o", str(tmp_path / "work")])
        assert code == 2
        assert "parent" in capsys.readouterr().err


class TestExportMdCommand:
    def test_bundle_from_transformed(self, tmp_path):
        demo = tmp_path / "demo"
        run_cli(["demo", "-o", str(demo)])
        out = tmp_path / "work"
        code = run_cli(["export-md", str(demo / "transformed.json"),
                        "-o", str(out)])
        assert code == 0
        assert (out / "bundle" / "INDEX.md").exists()
        assert (out / "markdown-report.json").exists()


class TestRunCommand:
    def test_md_only_from_existing_ir(self, tmp_path):
        demo = tmp_path / "demo"
        run_cli(["demo", "-o", str(demo)])
        out = tmp_path / "run"
        code = run_cli(["run", "--from", str(demo / "structure.json"),
                        "--md-only", "-o", str(out)])
        assert code == 0
        assert (out / "transformed.json").exists()
        assert (out / "bundle" / "INDEX.md").exists()

    def test_requires_url_or_from(self, capsys):
        code = run_cli(["run", "-o", "output"])
        assert code == 2
        assert "--from" in capsys.readouterr().err


class TestExtractGuards:
    def test_no_token_is_config_error(self, tmp_path, capsys, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        code = run_cli(["extract", "https://www.notion.so/x", "-o",
                        str(tmp_path / "work")])
        assert code == 2
        assert "NOTION_TOKEN" in capsys.readouterr().err
