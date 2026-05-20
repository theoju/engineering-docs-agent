from __future__ import annotations
import sys
from pathlib import Path

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


def test_verify_runner_imports():
    # Just ensure the module imports without error.
    import verify_runner  # noqa: F401

    assert hasattr(verify_runner, "run")
    assert hasattr(verify_runner, "main")
