from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from contracts import validate_and_parse  # noqa: E402

SCHEMAS = Path(__file__).parent.parent.parent / "agents" / "schemas"


def test_fact_checker_contradiction_output_validates():
    raw = {
        "ok": True,
        "verdict": "contradiction",
        "page": "docs/site-src/core/page.md",
        "findings": [
            {
                "claim": "page says partial runs never advance the baseline",
                "source_path": "scripts/runner.py",
                "evidence": "advance happens unconditionally at save_state()",
            }
        ],
    }
    parsed, reasons = validate_and_parse("fact-checker", raw)
    assert reasons == []
    assert parsed.verdict == "contradiction"
    assert parsed.findings[0]["source_path"] == "scripts/runner.py"


def test_fact_checker_minimal_output_validates_with_empty_findings():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "consistent"}
    )
    assert reasons == []
    assert parsed.findings == []


def test_fact_checker_bad_verdict_rejected():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "maybe"}
    )
    assert parsed is None
    assert any("schema_invalid" in r for r in reasons)


def test_page_author_schema_declares_evidence():
    schema = json.loads((SCHEMAS / "page_author.schema.json").read_text())
    assert "evidence" in schema["properties"]
    assert (
        schema["properties"]["evidence"]["properties"]["files_read"]["type"] == "array"
    )


def test_page_author_output_with_evidence_validates():
    raw = {
        "ok": True,
        "path": "docs/site-src/core/page.md",
        "action": "create",
        "evidence": {"files_read": ["scripts/real_module.py"]},
    }
    parsed, reasons = validate_and_parse("page-author", raw)
    assert reasons == []
    assert parsed.ok


# ---------- orchestrator wiring (dry-run fixtures) ----------

import orchestrator_runner  # noqa: E402


def _write_fakes(fakes: Path, *, with_fact_checker: bool = True) -> None:
    """Minimal dry-run fixture set for one PR -> one core page."""
    fakes.mkdir(parents=True, exist_ok=True)
    (fakes / "fake_source_collector.json").write_text(
        json.dumps(
            {
                "prs": [
                    {
                        "number": 1,
                        "url": "https://example.test/pr/1",
                        "merge_sha": "",
                        "files": [
                            {"path": "scripts/real_module.py"},
                            "plain_listed.py",
                        ],
                        "jira_keys": [],
                    }
                ],
                "jira_issues": [],
            }
        )
    )
    (fakes / "fake_pr_summarizer.json").write_text(
        json.dumps(
            {
                "pr_number": 1,
                "what_changed": "module behavior",
                "doc_targets": [
                    {"lens": "core", "page_hint": "page.md", "action": "create"}
                ],
            }
        )
    )
    (fakes / "fake_page_author.json").write_text(
        json.dumps(
            {"ok": True, "path": "docs/site-src/core/page.md", "action": "create"}
        )
    )
    (fakes / "fake_content_validator.json").write_text(
        json.dumps({"passed": [], "failed": []})
    )
    (fakes / "fake_gap_detector.json").write_text(
        json.dumps({"pr_id": "o/r#1", "needs_spec": False})
    )
    (fakes / "fake_notifier.json").write_text(
        json.dumps({"slack_ok": True, "email_ok": True})
    )
    if with_fact_checker:
        (fakes / "fake_fact_checker.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "verdict": "contradiction",
                    "page": "docs/site-src/core/page.md",
                    "findings": [
                        {
                            "claim": "page says X but code does Y",
                            "source_path": "scripts/real_module.py",
                            "evidence": "real_fn returns 1",
                        }
                    ],
                }
            )
        )


def _host_with_module(init_host, tmp_path) -> Path:
    """init_host + one committed source file the pages can cite."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text(
        "def real_fn():\n    return 1\n"
    )
    return init_host({"version": "1"})


def test_page_author_receives_source_paths(init_host, tmp_path, monkeypatch):
    _host_with_module(init_host, tmp_path)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    captured: dict = {}
    real = orchestrator_runner.dispatch_validated

    def spy(name, inputs, **kw):
        if name == "page-author":
            captured["inputs"] = inputs
        return real(name, inputs, **kw)

    monkeypatch.setattr(orchestrator_runner, "dispatch_validated", spy)
    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    assert captured["inputs"]["source_paths"] == [
        "plain_listed.py",
        "scripts/real_module.py",
    ]


CITED_PAGE = """\
---
status: draft
sources: []
synthesized_into: null
---
# Page

This page cites `scripts/real_module.py` in prose.
"""

UNCITED_PAGE = CITED_PAGE.replace(
    " cites `scripts/real_module.py` in", " has no citations in"
)


def _precreate_page(tmp_path: Path, text: str) -> Path:
    page = tmp_path / "docs" / "site-src" / "core" / "page.md"
    page.write_text(text)  # exists -> orchestrator takes the edit path
    return page


def test_fact_checker_dispatched_for_cited_page(init_host, tmp_path, read_current_run):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert len(cr["fact_check_warnings"]) == 1
    warning = cr["fact_check_warnings"][0]
    assert "docs/site-src/core/page.md" in warning
    assert "page says X but code does Y" in warning
    assert "scripts/real_module.py" in warning
    assert cr["partial"] is False  # warn layer never flips partial


def test_fact_checker_skipped_for_page_without_citations(
    init_host, tmp_path, read_current_run
):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, UNCITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes, with_fact_checker=False)  # dispatch would log a reason

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["fact_check_warnings"] == []
    assert not any("fact_checker" in r for r in cr["partial_reasons"])


def test_fact_checker_failure_is_info_only(init_host, tmp_path, read_current_run):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes, with_fact_checker=False)  # missing fixture = dispatch None

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["fact_check_warnings"] == []
    assert any(
        r.startswith("fact_checker_unavailable: docs/site-src/core/page.md")
        for r in cr["partial_reasons"]
    )
    assert cr["partial"] is False  # info_only: never flips partial


def test_fact_checker_consistent_verdict_yields_no_warnings(
    init_host, tmp_path, read_current_run
):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)
    (fakes / "fake_fact_checker.json").write_text(
        json.dumps({"ok": True, "verdict": "consistent", "findings": []})
    )

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    assert read_current_run(state_path)["fact_check_warnings"] == []


# ---------- PR body + notifier digest threading ----------


def test_compose_pr_body_renders_fact_warnings():
    body = orchestrator_runner._compose_pr_body(
        changed_files=["docs/site-src/core/page.md"],
        lens_paths={"core": "docs/site-src/core"},
        partial=False,
        partial_reasons=[],
        baseline_sha="a" * 40,
        current_sha="b" * 40,
        fact_warnings=["`docs/site-src/core/page.md`: claim (vs `scripts/x.py`)"],
    )
    assert "**Factual-accuracy warnings:**" in body
    assert "- `docs/site-src/core/page.md`: claim (vs `scripts/x.py`)" in body


def test_compose_pr_body_warnings_alone_render():
    body = orchestrator_runner._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
        fact_warnings=["w1"],
    )
    assert "Factual-accuracy warnings" in body
    assert body != "docs-agent run"


def test_compose_pr_body_no_warnings_keeps_legacy_sentinel():
    body = orchestrator_runner._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    assert body == "docs-agent run"


def test_run_threads_fact_warnings_to_pr_and_digest(init_host, tmp_path, monkeypatch):
    _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    seen_pr: dict = {}

    def fake_open(repo_root, gh, **kw):
        seen_pr.update(kw)
        return 1, []

    monkeypatch.setattr(orchestrator_runner, "open_or_append_pr", fake_open)

    seen_notifier: dict = {}
    real = orchestrator_runner.dispatch_validated

    def spy(name, inputs, **kw):
        if name == "notifier":
            seen_notifier.update(inputs)
        return real(name, inputs, **kw)

    monkeypatch.setattr(orchestrator_runner, "dispatch_validated", spy)

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=False)
    assert rc == 0
    assert len(seen_pr["fact_warnings"]) == 1
    assert "page says X but code does Y" in seen_pr["fact_warnings"][0]
    assert seen_notifier["digest"]["fact_check_warnings"] == seen_pr["fact_warnings"]
