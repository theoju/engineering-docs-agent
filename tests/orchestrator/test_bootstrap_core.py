from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_page_target_is_editable():
    globs = ["docs/site-src/**"]
    assert runner._page_target_is_editable("docs/site-src/core/api.md", globs) is True
    assert runner._page_target_is_editable("scripts/x.py", globs) is False
    # No globs configured -> permissive (matches the nightly loop's behavior).
    assert runner._page_target_is_editable("anything/at/all.md", []) is True
