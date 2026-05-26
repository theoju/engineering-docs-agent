from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_agent_runtime_does_not_import_playwright():
    """Importing the orchestrator entrypoint must not drag Playwright (a
    docs-tooling dep) into the stdlib agent runtime."""
    code = (
        "import sys; sys.path.insert(0, %r);"
        "import orchestrator_runner;"
        "assert 'playwright' not in sys.modules, 'agent runtime imported playwright';"
        "print('clean')" % str(SCRIPTS)
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "clean" in r.stdout


def test_verify_diagrams_imports_without_playwright():
    """The gate module imports even when Playwright is absent; the guard sets
    _PLAYWRIGHT_AVAILABLE rather than crashing at import."""
    code = (
        "import sys; sys.path.insert(0, %r);"
        "import verify_diagrams as vd;"
        "assert hasattr(vd, '_PLAYWRIGHT_AVAILABLE');"
        "assert vd.scan_mermaid_sources.__module__ == 'verify_diagrams';"
        "print('ok')" % str(SCRIPTS)
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout
