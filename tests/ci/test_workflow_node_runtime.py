"""Guard: CI workflows must pin action majors that run on a supported Node.

GitHub forces Node 24 on its runners from 2026-06-02; `actions/checkout@v4`
and `actions/setup-python@v5` bundle the deprecated Node 20 and will hard-fail
after that date. The first majors that ship Node 24 are checkout@v5 and
setup-python@v6 (`runs.using: node24`). This test fails the moment any
workflow drops below those floors, so the deprecation cannot creep back in.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WF_DIR = ROOT / ".github" / "workflows"
_TPL_DIR = ROOT / "templates"
# Repo workflows + scaffolded workflow templates (templates/workflow-*.yml).
# Templates are copied verbatim to host repos, so they must meet the same floor.
WORKFLOWS = sorted(
    [*_WF_DIR.glob("*.yml"), *_WF_DIR.glob("*.yaml"), *_TPL_DIR.glob("workflow-*.yml")]
)

# Minimum major version whose `runs.using` is node24, per action.
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
    "actions/upload-pages-artifact": 5,
}

_USES = re.compile(r"uses:\s*(actions/[\w-]+)@v(\d+)")


def test_workflows_exist():
    # Sanity: discovery is glob-based, so an empty match would vacuously pass.
    assert WORKFLOWS, "no workflow files found under .github/workflows/"


def test_no_workflow_pins_a_node20_action_major():
    violations = []
    for wf in WORKFLOWS:
        for action, major in _USES.findall(wf.read_text()):
            floor = NODE24_FLOOR.get(action)
            if floor is not None and int(major) < floor:
                violations.append(f"{wf.name}: {action}@v{major} (needs >= v{floor})")
    assert not violations, "Node-20 action majors found:\n" + "\n".join(violations)


def test_pages_deploy_workflows_disable_jekyll():
    """Any workflow that deploys Pages must publish the artifact verbatim
    (.nojekyll) and never invoke the legacy Jekyll build."""
    offenders = []
    for wf in WORKFLOWS:
        text = wf.read_text()
        if "actions/deploy-pages" not in text:
            continue
        if ".nojekyll" not in text:
            offenders.append(f"{wf.name}: deploys Pages but never writes .nojekyll")
        if "jekyll" in text.lower().replace(".nojekyll", ""):
            offenders.append(f"{wf.name}: references legacy Jekyll")
    assert not offenders, "\n".join(offenders)


def test_upload_pages_artifact_in_node24_floor():
    """Regression guard: `actions/upload-pages-artifact` must carry a Node-24 floor.

    v4 of this action shipped Node 20 (deprecated June 2026); v5 is the first
    Node-24 major. The template-validity test (test_workflow_pages_template.py)
    pins the template to @v5, but without this floor entry a host or this repo
    could drift to @v4 on this single action and the runtime guard would
    silently pass — exactly the symmetry gap CCE-34 called out.
    """
    assert NODE24_FLOOR.get("actions/upload-pages-artifact") == 5
