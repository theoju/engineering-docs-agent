from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPTS_LINT = Path(__file__).parent.parent.parent / "scripts" / "lint"
SCRIPT = SCRIPTS_LINT / "citation_line_free.py"


def _cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    return cfg


def _run(paths: list[Path], cfg: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_line_pin_warns_but_does_not_fail(tmp_path):
    cfg = _cfg(tmp_path)
    page = tmp_path / "p.md"
    page.write_text("The entry is `scripts/orchestrator_runner.py:1240` today.\n")
    rc, out = _run([page], cfg)
    assert out["rule"] == "citation_line_free"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is False
    assert "scripts/orchestrator_runner.py:1240" in out["results"][0]["message"]


def test_clean_page_passes(tmp_path):
    cfg = _cfg(tmp_path)
    page = tmp_path / "p.md"
    page.write_text("The entry is `scripts/orchestrator_runner.py:run` today.\n")
    rc, out = _run([page], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
