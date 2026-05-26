# conftest.py
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.live tests unless `-m live` is passed on the command line.

    Live tests cost ~$1-3 per full pass and need real auth (OAuth or
    ANTHROPIC_API_KEY). They must never run by accident on `pytest -q` or in
    CI's regular suite.
    """
    marker_expr = config.getoption("markexpr") or ""
    if "live" in marker_expr:
        return  # user explicitly opted in; collect normally
    skip_live = pytest.mark.skip(
        reason="live test — run with `pytest -m live` to opt in"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
