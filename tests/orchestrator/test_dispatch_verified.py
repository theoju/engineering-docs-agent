from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def _fake_dispatch_validated_ok(name, inputs, *, dry_run_dir, cwd=None):
    return ({"ok": True, "path": inputs["target_path"]}, [])


def _fake_dispatch_validated_invalid(name, inputs, *, dry_run_dir, cwd=None):
    return (None, ["schema_invalid: page-author: bad shape"])


def test_dispatch_verified_passes_through_when_post_write_check_is_none(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")
    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=None,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out == {"ok": True, "path": str(target)}
    assert reasons == []
    assert target.exists()  # not deleted


def test_dispatch_verified_short_circuits_on_dispatch_validated_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_invalid)
    target = tmp_path / "page.md"
    target.write_text("body")
    sentinel = {"called": False}

    def check(_target, _page):
        sentinel["called"] = True
        return False, ["should_not_run"]

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out is None
    assert reasons == ["schema_invalid: page-author: bad shape"]
    assert sentinel["called"] is False
    assert target.exists()  # untouched on schema-invalid


def test_dispatch_verified_returns_output_when_check_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")

    def check(t, _p):
        return True, []

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out == {"ok": True, "path": str(target)}
    assert reasons == []
    assert target.exists()


def test_dispatch_verified_deletes_target_and_returns_reasons_when_check_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")

    def check(t, _p):
        return False, [f"description_quality: {t.name}: min_words: 2 < 6"]

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out is None
    assert any("description_quality" in r for r in reasons)
    assert not target.exists()  # deleted so next bootstrap run retries it


def test_dispatch_verified_raises_when_check_is_set_without_target_path(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)

    def check(_t, _p):
        return True, []

    with pytest.raises(ValueError, match="target_path is required"):
        runner.dispatch_verified(
            "page-author",
            {"target_path": "ignored"},
            dry_run_dir=None,
            cwd=tmp_path,
            post_write_check=check,
            target_path=None,
        )
