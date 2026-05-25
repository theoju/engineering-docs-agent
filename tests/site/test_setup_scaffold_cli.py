from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"


def test_cli_scaffolds_default_template(tmp_path: Path):
    # a python file present → mkdocstrings should be wired
    (tmp_path / "thing.py").write_text("x = 1\n")
    proc = subprocess.run(
        [
            sys.executable,
            str(_CLI),
            "--repo-root",
            str(tmp_path),
            "--site-name",
            "Demo",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "docs/site-src/index.md").exists()
    assert (tmp_path / "docs/site-src/archive/index.md").exists()
    assert (tmp_path / "mkdocs.yml").exists()
    assert "mkdocstrings" in (tmp_path / "mkdocs.yml").read_text()


def test_cli_rerun_is_idempotent(tmp_path: Path):
    cmd = [
        sys.executable,
        str(_CLI),
        "--repo-root",
        str(tmp_path),
        "--site-name",
        "Demo",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    (tmp_path / "docs/site-src/index.md").write_text("authored\n")
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert (tmp_path / "docs/site-src/index.md").read_text() == "authored\n"
