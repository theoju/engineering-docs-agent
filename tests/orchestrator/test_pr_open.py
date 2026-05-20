from __future__ import annotations
import sys
from pathlib import Path

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from orchestrator_runner import branch_name  # noqa: E402


def test_branch_name_uses_utc_date():
    assert branch_name("2026-05-20T07:00:00+00:00") == "docs-agent/2026-05-20T07"


def test_branch_name_handles_z_suffix():
    assert branch_name("2026-12-31T23:59:59Z") == "docs-agent/2026-12-31T23"


def test_branch_name_includes_hour():
    from orchestrator_runner import branch_name

    assert branch_name("2026-05-20T07:00:00Z") == "docs-agent/2026-05-20T07"


def test_branch_name_handles_short_iso():
    from orchestrator_runner import branch_name

    assert branch_name("2026-05-20T07") == "docs-agent/2026-05-20T07"
