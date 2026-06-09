"""CCE-104 / CCE-106: the orchestrator's deterministic site-generator stage.

run_site_generators runs the spec generators (archive capability D + contracts +
section overviews) when the host config has a site: block, is a clean no-op when
it doesn't, and is best-effort — a generator that raises records an info_only
partial and never propagates (so the nightly PR is never blocked by an advisory
stage).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

import archive_indexes  # noqa: E402
import orchestrator_runner  # noqa: E402
import section_overview  # noqa: E402


def _spec(dir_: Path, name: str, title: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / name).write_text(
        f"---\ntitle: {title}\nstatus: draft\n---\n\n# {title}\n\nOne-line summary.\n",
        encoding="utf-8",
    )


def _site_config(sources: list[str]) -> dict:
    return {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {
                    "key": "archive",
                    "path": "archive/",
                    "title": "Decision Archive",
                    "generator": "archive-index",
                    "sources": sources,
                }
            ],
        }
    }


def test_writes_archive_page_per_source(tmp_path):
    _spec(tmp_path / "docs/superpowers/specs", "2026-01-01-alpha.md", "Alpha")
    config = _site_config(["docs/superpowers/specs"])

    result = orchestrator_runner.run_site_generators(tmp_path, config, {})

    page = tmp_path / "docs/site-src/archive/specs.md"
    assert page.exists(), "archive/specs.md should be generated from the source dir"
    assert "Alpha" in page.read_text(encoding="utf-8")
    assert result["archive"]["written"] == ["docs/site-src/archive/specs.md"]


def test_no_site_block_is_noop(tmp_path):
    state: dict = {}
    result = orchestrator_runner.run_site_generators(
        tmp_path, {"docs": {"framework": "mkdocs"}}, state
    )
    assert result == {"archive": None, "contracts": None, "overviews": None}
    assert not (tmp_path / "docs/site-src/archive").exists()
    # an absent site: block is a clean skip, not a degradation
    assert state.get("current_run", {}).get("partial_reasons", []) == []


def test_generator_exception_is_best_effort(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(archive_indexes, "generate_archive", _boom)
    state: dict = {}

    # must NOT raise — the advisory stage swallows and records
    result = orchestrator_runner.run_site_generators(
        tmp_path, _site_config(["docs/superpowers/specs"]), state
    )

    assert result["archive"] is None
    reasons = state["current_run"]["partial_reasons"]
    assert any("archive_generate_failed" in r for r in reasons)
    # info_only: a failed advisory generator must NOT mark the whole run partial
    assert state["current_run"]["partial"] is False


# --- CCE-106: section overviews wired into run_site_generators ---


def _dir_section_config(tmp_path: Path) -> dict:
    """Config with a directory section that has a child page.

    Creates:
      docs/site-src/topics/index.md       (section landing)
      docs/site-src/topics/alpha.md       (child page)
    so generate_overviews has content to list.
    """
    section_dir = tmp_path / "docs/site-src/topics"
    section_dir.mkdir(parents=True, exist_ok=True)
    (section_dir / "index.md").write_text(
        "---\ntitle: Topics\n---\n\n# Topics\n", encoding="utf-8"
    )
    (section_dir / "alpha.md").write_text(
        "---\ntitle: Alpha\n---\n\n# Alpha\n", encoding="utf-8"
    )
    return {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {
                    "key": "topics",
                    "path": "topics/",
                    "title": "Topics",
                },
            ],
        }
    }


def test_run_site_generators_runs_overviews_after_archive_and_contracts(tmp_path):
    """generate_overviews is called and its ledger surfaced in the result dict."""
    config = _dir_section_config(tmp_path)
    state: dict = {}

    result = orchestrator_runner.run_site_generators(tmp_path, config, state)

    assert "overviews" in result
    assert result["overviews"] is not None
    assert isinstance(result["overviews"].get("written"), list)


def test_run_site_generators_swallows_overview_failure(tmp_path, monkeypatch):
    """A generate_overviews exception records an info_only partial and never raises."""

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(section_overview, "generate_overviews", _boom)
    config = {"site": {"docs_dir": "docs/site-src", "sections": []}}
    state: dict = {}

    # must NOT raise
    result = orchestrator_runner.run_site_generators(tmp_path, config, state)

    assert result.get("overviews") is None
    reasons = state["current_run"]["partial_reasons"]
    assert any("overview" in r.lower() for r in reasons)
    # info_only: must NOT flip the run to partial
    assert state["current_run"]["partial"] is False
