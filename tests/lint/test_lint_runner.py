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


def test_tier2_spec_keys_activate_rules(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("""
lint:
  tier1: default
  tier2:
    banned_phrases: ["simply"]
    ai_tells: true
    terminology_glossary: glossary.yml
    second_person_consistency: true
    paragraph_max_words: 150
  tier3: {}
""")
    from scripts.lint.lint_runner import enabled_rules
    import yaml

    rules = enabled_rules(yaml.safe_load(cfg.read_text()))
    # Tier 1 default rules + Tier 2 keyed-in rules
    assert "banned_phrases" in rules
    assert "ai_tells" in rules
    assert "terminology" in rules
    assert "second_person" in rules
    assert "paragraph_length" in rules
    assert "voice_consistency" not in rules  # excluded: LLM-handled
