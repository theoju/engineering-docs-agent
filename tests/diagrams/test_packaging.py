from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_requirements_docs_declares_playwright_and_mkdocs():
    txt = (ROOT / "requirements-docs.txt").read_text().lower()
    assert "playwright" in txt
    assert "mkdocs" in txt  # building the site is part of the gate's CI job


def test_requirements_docs_separate_from_agent_runtime():
    # The agent runtime stays stdlib + pyyaml + jsonschema; playwright must not
    # leak into a general requirements.txt if one exists.
    rt = ROOT / "requirements.txt"
    if rt.exists():
        assert "playwright" not in rt.read_text().lower()


def test_makefile_has_docs_verify_target():
    mk = (ROOT / "Makefile").read_text()
    assert "docs-verify:" in mk
    assert "verify_diagrams.py" in mk


def test_docs_workflow_runs_the_gate():
    import yaml  # already a runtime dep

    wf = ROOT / ".github" / "workflows" / "docs.yml"
    data = yaml.safe_load(wf.read_text())
    # `on:` may parse as the boolean True key in YAML 1.1 — accept either.
    triggers = data.get("on") or data.get(True)
    assert triggers, "workflow must declare triggers"
    body = wf.read_text()
    assert "playwright install" in body
    assert "verify_diagrams.py" in body
    assert "--require" in body  # CI must hard-fail when Playwright is missing
    assert "mkdocs build" in body
    # The tests/diagrams suite includes the runtime-isolation test, which
    # imports the agent runtime (orchestrator_runner -> state_io -> jsonschema)
    # in a subprocess; the CI env must install jsonschema or that import fails.
    assert "jsonschema" in body


def test_docs_workflow_has_no_pull_request_paths_filter():
    """CCE-91: diagram-gate is a required branch-protection check. A
    workflow-level `paths:` filter on the pull_request trigger causes GitHub
    to skip the workflow entirely when no listed paths change, which means
    the required check never reports and PRs stay BLOCKED forever. Heavy
    steps must instead be gated by an in-job changed-files filter so the
    job always reports a status. Same pattern as actionlint.yml (CCE-59).
    """
    import yaml

    wf = ROOT / ".github" / "workflows" / "docs.yml"
    data = yaml.safe_load(wf.read_text())
    triggers = data.get("on") or data.get(True)
    pr = triggers.get("pull_request") or {}
    assert "paths" not in pr, (
        "docs.yml.on.pull_request must NOT carry a `paths:` filter — "
        "diagram-gate is a required check; a workflow-level skip permanently "
        "blocks merge on PRs that don't touch the listed paths. Gate heavy "
        "steps inside the job with a changed-files detection step instead. "
        "See CCE-91 and the matching invariant on actionlint.yml (CCE-59)."
    )
    assert "paths-ignore" not in pr, (
        "Same blocker — paths-ignore at workflow level can also produce "
        "permanent BLOCKED on the inverse case."
    )


def test_docs_workflow_gates_heavy_steps_on_in_job_filter():
    """CCE-91 companion: confirm the in-job filter step exists and that the
    expensive steps (Playwright install, mkdocs build, gate run) are gated
    on its output. Without this gate, removing the workflow-level paths
    filter would run Chromium + mkdocs on every non-docs PR — fast PRs
    would slow from ~30s to ~3min.
    """
    import yaml

    wf = ROOT / ".github" / "workflows" / "docs.yml"
    data = yaml.safe_load(wf.read_text())
    steps = data["jobs"]["diagram-gate"]["steps"]
    filter_step = next((s for s in steps if s.get("id") == "filter"), None)
    assert filter_step is not None, "docs.yml must declare a `filter` step (id: filter)"
    # The expensive steps — matched by name — must each carry an `if:` that
    # references the filter output. Matching by name (not run content) avoids
    # the false-positive where the filter step itself references
    # `verify_diagrams.py` as part of its path-pattern matcher.
    expensive_step_name_fragments = (
        "Install Chromium for Playwright",
        "Run diagram render tests",
        "Build the docs site",
        "Diagram render gate",
        "Install docs tooling",
    )
    for s in steps:
        name = s.get("name", "") or ""
        if any(frag in name for frag in expensive_step_name_fragments):
            cond = s.get("if", "")
            assert "steps.filter.outputs.relevant" in cond, (
                f"expensive step {name!r} is not gated on "
                f"steps.filter.outputs.relevant — every non-docs PR would "
                f"pay its cost. Add `if: steps.filter.outputs.relevant == 'true'`."
            )
