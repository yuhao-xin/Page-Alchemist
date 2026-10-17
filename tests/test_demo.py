"""Demo mode: synthetic document shape and full-run determinism."""
from __future__ import annotations

import json
from pathlib import Path

from notion_alchemist.demo import build_demo_document, run_demo
from notion_alchemist.transform import RETUNE_EMOJI, transform_document


class TestBuildDemoDocument:
    def test_shape(self, tmp_path):
        doc = build_demo_document(tmp_path / "assets")
        assert sum(1 for _ in doc.iter_pages()) == 3
        assert doc.engine in ("api", "export")
        root = doc.pages[0]
        assert root.children, "demo must have nested pages"

    def test_carries_the_mess_transform_cleans(self, tmp_path):
        doc = build_demo_document(tmp_path / "assets")
        types_seq = [b.type for b in doc.pages[0].blocks]
        assert "table_of_contents" in types_seq          # noise to drop
        assert "synced_block" in types_seq               # block to unwrap
        assert any(rt.color != "default"
                   for b in doc.pages[0].blocks
                   for rt in list(b.text) + list(b.caption))
        assert doc.pages[0].database                     # database to rebuild

    def test_local_image_asset_exists(self, tmp_path):
        assets = tmp_path / "assets"
        doc = build_demo_document(assets)
        images = [b for b in doc.pages[0].blocks if b.type == "image"]
        assert images
        local = images[1].asset.get("local_path")   # second image is local
        assert local
        path = Path(local)
        assert (path if path.is_absolute() else assets / path).exists()

    def test_title_carries_brand_prefix(self, tmp_path):
        doc = build_demo_document(tmp_path / "assets")
        assert "Second Brain OS" in doc.pages[0].title
        assert "【付费】" in doc.pages[0].title or "付费" in doc.pages[0].title


class TestRunDemo:
    def test_all_artifacts_written(self, tmp_path):
        out = tmp_path / "demo"
        summary = run_demo(out)
        assert summary["pages"] == 3
        for name in ("structure.json", "transformed.json",
                     "transform-report.json", "publish-report.json",
                     "markdown-report.json", "demo-summary.json"):
            assert (out / name).exists(), name
        assert (out / "bundle" / "INDEX.md").exists()

    def test_publish_plan_is_dry(self, tmp_path):
        out = tmp_path / "demo"
        summary = run_demo(out)
        assert "created" in summary["publish_plan"]
        report = json.loads((out / "publish-report.json").read_text("utf-8"))
        assert report["errors"] == []

    def test_deterministic_across_runs(self, tmp_path):
        import json
        a = run_demo(tmp_path / "a")
        b = run_demo(tmp_path / "b")
        assert a["blocks"] == b["blocks"]
        assert a["transform"] == b["transform"]
        # the markdown summary embeds the output dir; compare the counts
        ra = json.loads((tmp_path / "a" / "markdown-report.json")
                        .read_text("utf-8"))
        rb = json.loads((tmp_path / "b" / "markdown-report.json")
                        .read_text("utf-8"))
        assert ra["pages"] == rb["pages"]
        assert ra["csv_files"] == rb["csv_files"]
        assert ra["assets"] == rb["assets"]

    def test_transform_applied_to_demo(self, tmp_path):
        out = tmp_path / "demo"
        run_demo(out)
        doc = json.loads((out / "transformed.json").read_text("utf-8"))
        assert "【付费】" not in doc["pages"][0]["title"]
        assert doc["pages"][0]["icon"] in RETUNE_EMOJI
        types_seq = [b["type"] for b in doc["pages"][0]["blocks"]]
        assert "table_of_contents" not in types_seq
        assert doc["pages"][0]["blocks"][0]["type"] == "callout"  # archive card
