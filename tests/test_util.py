"""Utilities: id parsing, slugs, hashing, rate limiting, dotenv."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from page_alchemist.util import (RateLimiter, backoff_delay,
                                   extract_notion_id, format_uuid,
                                   load_dotenv, safe_filename, sha1_bytes,
                                   sha1_file, slugify)

HEX32 = "0123456789abcdef0123456789abcdef"


class TestExtractNotionId:
    def test_dashed_uuid_passthrough(self):
        assert extract_notion_id(HEX32[:8] + "-" + HEX32[8:12] + "-" +
                                 HEX32[12:16] + "-" + HEX32[16:20] + "-" +
                                 HEX32[20:]) == format_uuid(HEX32)

    def test_bare_hex32(self):
        assert extract_notion_id(HEX32) == format_uuid(HEX32)

    def test_notion_so_url(self):
        url = "https://www.notion.so/workspace/Page-Title-" + HEX32
        assert extract_notion_id(url) == format_uuid(HEX32)

    def test_url_with_query_and_slash(self):
        url = "https://www.notion.so/Page-" + HEX32 + "?pvs=4"
        assert extract_notion_id(url) == format_uuid(HEX32)

    def test_custom_domain(self):
        url = "https://team.notion.site/Page-" + HEX32
        assert extract_notion_id(url) == format_uuid(HEX32)

    def test_uppercase_hex(self):
        assert extract_notion_id(HEX32.upper()) == format_uuid(HEX32)

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="could not extract"):
            extract_notion_id("not a notion link at all")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            extract_notion_id("   ")


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_cjk_preserved(self):
        # Chinese characters are slug-legal in this project
        assert slugify("我的笔记") == "我的笔记"

    def test_collapse_and_trim(self):
        assert slugify("  --Weird__Name!!  ") == "weird-name"

    def test_max_len(self):
        out = slugify("a" * 100, max_len=10)
        assert len(out) <= 10 and not out.endswith("-")

    def test_empty(self):
        assert slugify("***") == ""


class TestSafeFilename:
    def test_illegal_chars(self):
        assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_empty_falls_back(self):
        assert safe_filename("   ", default="file") == "file"

    def test_dots_trimmed(self):
        assert safe_filename("  ...name...  ") == "name"


class TestHashing:
    def test_sha1_bytes_known_value(self):
        assert sha1_bytes(b"abc") == ("a9993e364706816aba3e25717850c26c"
                                      "9cd0d89d")

    def test_sha1_file_matches_bytes(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"abc")
        assert sha1_file(p) == sha1_bytes(b"abc")


class TestRateLimiter:
    def test_zero_rps_never_sleeps(self):
        limiter = RateLimiter(0)
        start = time.monotonic()
        for _ in range(5):
            limiter.wait()
        assert time.monotonic() - start < 0.05

    def test_min_interval_enforced(self):
        limiter = RateLimiter(50)  # 20ms interval
        limiter.wait()
        start = time.monotonic()
        limiter.wait()
        assert time.monotonic() - start >= 0.015


class TestBackoff:
    def test_grows_and_caps(self):
        assert backoff_delay(1, base=1.0, cap=30.0) >= 1.0
        assert backoff_delay(10, base=1.0, cap=30.0) <= 30.25

    def test_jitter_is_bounded(self):
        for _ in range(20):
            d = backoff_delay(3, base=1.0, cap=30.0)
            assert 4.0 <= d <= 4.25


class TestDotenv:
    def test_load_and_no_override(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("NA_TEST_KEY=hello\n# comment\n\nNA_Q=\"quoted\"\n",
                       encoding="utf-8")
        os.environ.pop("NA_TEST_KEY", None)
        os.environ.pop("NA_Q", None)
        assert load_dotenv(env) is True
        assert os.environ["NA_TEST_KEY"] == "hello"
        assert os.environ["NA_Q"] == "quoted"
        os.environ["NA_TEST_KEY"] = "keep"
        load_dotenv(env, override=False)
        assert os.environ["NA_TEST_KEY"] == "keep"
        os.environ.pop("NA_TEST_KEY", None)
        os.environ.pop("NA_Q", None)

    def test_missing_file_returns_false(self, tmp_path):
        assert load_dotenv(tmp_path / "nope.env") is False
