from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))
import description_quality  # noqa: E402


_DEFAULT_CONFIG: dict = {"lint": {"tier1": "default"}}


def test_check_fm_passes_for_substantial_description():
    fm = {"description": "Pulls merged PRs and Jira issues from the configured window."}
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
    assert ok, msg
    assert msg == "ok"


def test_check_fm_rejects_below_min_words():
    fm = {"description": "Source-collector capability."}  # 2 words
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
    assert not ok
    assert "min_words" in msg


def test_check_fm_rejects_equal_to_title():
    fm = {"description": "Source collector"}
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
    assert not ok
    assert "equal_to_title" in msg


def test_check_fm_rejects_trailing_colon():
    fm = {"description": "Pulls merged PRs and Jira issues from the window:"}
    ok, msg = description_quality.check_fm(fm, title="X", config=_DEFAULT_CONFIG)
    assert not ok
    assert "trailing_colon" in msg


def test_check_fm_rejects_missing_description_field():
    fm = {"status": "draft"}
    ok, msg = description_quality.check_fm(fm, title="X", config=_DEFAULT_CONFIG)
    assert not ok
    assert "missing" in msg


def test_check_fm_with_title_none_skips_equal_to_title_check():
    # When the title is unknown (e.g. body has no H1 yet), the equal-to-title
    # comparison is skipped; the other checks still apply.
    fm = {"description": "Pulls merged PRs and Jira issues from the configured window."}
    ok, msg = description_quality.check_fm(fm, title=None, config=_DEFAULT_CONFIG)
    assert ok, msg


def test_check_fm_respects_min_words_config_override():
    cfg = {"lint": {"tier1": {"description_quality": {"min_words": 2}}}}
    fm = {"description": "Two words."}  # 2 words, normally too short
    ok, msg = description_quality.check_fm(fm, title="X", config=cfg)
    assert ok, msg


def test_check_fm_respects_forbid_trailing_colon_disabled():
    cfg = {"lint": {"tier1": {"description_quality": {"forbid_trailing_colon": False}}}}
    fm = {"description": "Pulls merged PRs from the configured window:"}
    ok, msg = description_quality.check_fm(fm, title="X", config=cfg)
    assert ok, msg
