"""Validate every directory under tests/fixtures/host_onboarding/ as a host
that could be committed to main. Each fixture's `.engineering-docs-agent/config.yml`
is run through the production loader so any host we ship in a runbook passes the
same checks the orchestrator runs at startup. CCE-58.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

# Make the production scripts package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from state_io import load_config_validated  # noqa: E402


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "host_onboarding"


def _host_dirs() -> list[Path]:
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(p for p in FIXTURE_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("host_dir", _host_dirs(), ids=lambda p: p.name)
def test_host_config_validates(host_dir: Path) -> None:
    cfg_path = host_dir / ".engineering-docs-agent" / "config.yml"
    assert cfg_path.exists(), f"missing config.yml at {cfg_path}"
    cfg = load_config_validated(cfg_path)

    # Smoke checks: every host fixture must declare the bare minimum the
    # publish-verifier needs.
    assert isinstance(cfg.get("publishing", {}).get("build_workflow"), str)
    assert cfg["publishing"]["build_workflow"].strip()

    # If ci_provider is set, it must be one of the schema-allowed values.
    ci = cfg["publishing"].get("ci_provider")
    if ci is not None:
        assert ci in ("github", "circleci"), f"unexpected ci_provider {ci!r}"


def test_at_least_one_host_fixture_exists() -> None:
    """Guards against an empty fixture tree silently passing the parametrized
    test with zero parameter cases."""
    assert _host_dirs(), "expected at least one host fixture directory"
