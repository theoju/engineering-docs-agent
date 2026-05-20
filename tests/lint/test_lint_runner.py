from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

RUNNER = Path(__file__).parent.parent.parent / "scripts" / "lint" / "lint_runner.py"
GOOD_FM = Path(__file__).parent.parent / "fixtures" / "frontmatter_schema" / "good.md"
BAD_FM = (
    Path(__file__).parent.parent
    / "fixtures"
    / "frontmatter_schema"
    / "bad_missing_field.md"
)


def test_runs_tier1_default(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier1: default\n  tier2: {}\n  tier3: {}\n")
    r = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--config",
            str(cfg),
            "--paths",
            str(GOOD_FM),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    rules_run = {result["rule"] for result in out["results"]}
    assert "frontmatter_schema" in rules_run
    assert "internal_links" in rules_run
    assert "markdown_hygiene" in rules_run


def test_aggregates_failure(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier1: default\n  tier2: {}\n  tier3: {}\n")
    r = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--config",
            str(cfg),
            "--paths",
            str(BAD_FM),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert any(not res["ok"] for result in out["results"] for res in result["results"])


def test_no_tier1_means_no_rules(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier2: {}\n  tier3: {}\n")
    fake = tmp_path / "f.md"
    fake.write_text("# x")
    r = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--config",
            str(cfg),
            "--paths",
            str(fake),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["results"] == []
