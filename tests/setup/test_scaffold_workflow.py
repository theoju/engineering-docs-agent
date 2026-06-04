"""Tests for scripts/scaffold_workflow.py — cron-randomization helper.

Determinism + bounds + anchor sanity + real-template round-trip + CLI smoke +
explicit-substring lock against the CI1 regex-spacing bug.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "scaffold_workflow.py"
TEMPLATE = ROOT / "templates" / "workflow-run.yml"

sys.path.insert(0, str(ROOT / "scripts"))


def test_deterministic_cron_minute_stable() -> None:
    """Same input → same output. No drift across calls."""
    from scaffold_workflow import deterministic_cron_minute

    assert deterministic_cron_minute("theoju", "adis") == deterministic_cron_minute(
        "theoju", "adis"
    )
    assert deterministic_cron_minute("theoju", "ccsa") == deterministic_cron_minute(
        "theoju", "ccsa"
    )


def test_known_fixture_minutes() -> None:
    """Lock specific (owner, repo) → minute integer values. Algorithm drift in
    deterministic_cron_minute will surface here. Regenerate the integers via:

        python3 -c "import hashlib; print(int(hashlib.sha256(b'theoju/adis').hexdigest(), 16) % 51 + 5)"
    """
    from scaffold_workflow import deterministic_cron_minute

    # Hardcoded — NOT a mirror of the algorithm. Algorithm drift = test failure.
    expected = {
        ("theoju", "adis"): 37,
        ("theoju", "ccsa"): 44,
        ("theoju", "data-importer"): 35,
        ("theoju", "dogfood"): 25,
    }
    for (owner, repo), minute in expected.items():
        assert deterministic_cron_minute(owner, repo) == minute, (
            f"{owner}/{repo}: expected {minute}, got {deterministic_cron_minute(owner, repo)}"
        )


def test_cron_minute_bounds() -> None:
    """Sweep — every minute must land in [5, 55]."""
    from scaffold_workflow import deterministic_cron_minute

    fixtures = [
        ("theoju", "adis"),
        ("theoju", "ccsa"),
        ("theoju", "data-importer"),
        ("theoju", "dogfood"),
        ("acme", "service-x"),
        ("contoso", "monorepo"),
        ("foo", "bar"),
        ("xyz", "lorem-ipsum"),
    ]
    for owner, repo in fixtures:
        m = deterministic_cron_minute(owner, repo)
        assert 5 <= m <= 55, f"{owner}/{repo}: minute {m} outside [5, 55]"


def test_rewrite_cron_anchor_zero_matches_raises() -> None:
    """A template without the anchored cron line must raise loudly."""
    from scaffold_workflow import rewrite_cron

    text = "name: docs-agent run\non:\n  workflow_dispatch:\n"
    with pytest.raises(RuntimeError, match=r"found 0"):
        rewrite_cron(text, "theoju", "dogfood")


def test_rewrite_cron_anchor_two_matches_raises() -> None:
    """A template with duplicate cron lines must also raise."""
    from scaffold_workflow import rewrite_cron

    text = 'on:\n  schedule:\n    - cron: "7 7 * * *"\n    - cron: "7 7 * * *"\n'
    with pytest.raises(RuntimeError, match=r"found 2"):
        rewrite_cron(text, "theoju", "dogfood")


def test_rewrite_cron_preserves_spacing_CI1_regression() -> None:
    """CI1 (3-validator panel finding): the regex must preserve the space between
    the minute and the first `*`. The pre-fix regex produced `42 7* * *`.
    Lock the exact rendered substring to prevent regression.
    """
    from scaffold_workflow import deterministic_cron_minute, rewrite_cron

    text = 'on:\n  schedule:\n    - cron: "7 7 * * *"\n'
    minute = deterministic_cron_minute("theoju", "dogfood")
    result = rewrite_cron(text, "theoju", "dogfood")
    assert f'cron: "{minute} 7 * * *"' in result, (
        f"cron-line spacing broken (CI1 regression). Got: {result!r}"
    )


def test_rewrite_cron_round_trip_on_real_template() -> None:
    """Real template — output differs from input by exactly the cron line and
    parses cleanly under ruamel.yaml.

    Inline xfail guard: if Task 5 has not yet refreshed the template (cron is
    still '0 7 * * *'), this test xfails until the refresh lands.
    """
    ruamel = pytest.importorskip("ruamel.yaml")
    from scaffold_workflow import rewrite_cron

    raw = TEMPLATE.read_text()
    if '- cron: "7 7 * * *"' not in raw:
        pytest.xfail("CCE-80 plan task 5 sets cron to '7 7 * * *' in the template")

    rendered = rewrite_cron(raw, "theoju", "dogfood")
    raw_lines = raw.splitlines()
    rendered_lines = rendered.splitlines()
    diffs = [
        (i, a, b) for i, (a, b) in enumerate(zip(raw_lines, rendered_lines)) if a != b
    ]
    assert len(diffs) == 1, f"expected exactly 1 differing line; got {diffs}"
    _, before, after = diffs[0]
    assert 'cron: "7 7 * * *"' in before
    assert 'cron: "' in after
    # Whatever minute is in the rendered line, the trailing `* * *"` must persist intact.
    assert '* * *"' in after

    yaml = ruamel.YAML(typ="rt")
    yaml.load(rendered)  # raises on malformed YAML

    if shutil.which("actionlint") is None:
        pytest.skip("actionlint not on PATH")
    proc = subprocess.run(
        ["actionlint", "-"], input=rendered, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"actionlint failed:\n{proc.stdout}{proc.stderr}"


def test_cli_smoke() -> None:
    """Invoke the helper as a script. Inline xfail guard for pre-task-5 state."""
    if not TEMPLATE.exists() or '- cron: "7 7 * * *"' not in TEMPLATE.read_text():
        pytest.xfail("CCE-80 plan task 5 refreshes the template (cron + FN header)")

    from scaffold_workflow import deterministic_cron_minute

    proc = subprocess.run(
        [sys.executable, str(HELPER), "--owner", "theoju", "--repo", "dogfood"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout
    assert (
        "# Drop into the host repo at .github/workflows/docs-agent-nightly.yml" in out
    )
    minute = deterministic_cron_minute("theoju", "dogfood")
    assert f'- cron: "{minute} 7 * * *"' in out
