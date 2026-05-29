# CCE-57 onboarding-prep implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land plugin-side prep work for CCE-57 (onboarding `theoju/claude-code-self-assessment`, the first JS/TS host) so the user-gated steps reduce to a copy-paste runbook.

**Architecture:** Five additive changes, each scoped to one file or fixture. P1 fixes the broken non-dogfood workflow template; P2 adds toolchain detection; P3 adds a JS/TS fixture and tests; P4 adds a read-only `preflight_host.py` CLI; P5 writes the user runbook. No behavior changes to the orchestrator or to the dogfood host.

**Tech Stack:** Python 3.11 (stdlib + PyYAML), pytest, GitHub Actions YAML, Markdown.

---

## File structure

| File                                                         | Role                                                        |
| ------------------------------------------------------------ | ----------------------------------------------------------- |
| `templates/workflow-run.yml`                                 | P1: add plugin checkout step; orchestrator path.            |
| `scripts/setup_discover.py`                                  | P2: `detect_toolchain` + `discover` wiring.                 |
| `tests/fixtures/setup_repos/js_docusaurus/`                  | P3: new JS/TS fixture (5 small files).                      |
| `tests/setup/test_setup_discover.py`                         | P3: add toolchain tests.                                    |
| `scripts/preflight_host.py`                                  | P4: new read-only CLI.                                      |
| `tests/setup/test_preflight_host.py`                         | P4: CLI behavior tests.                                     |
| `skills/engineering-docs-agent-setup/SKILL.md`               | P2+P1 docs: mention toolchain block + plugin-checkout step. |
| `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md` | P5: user runbook.                                           |

---

## Task 1: P1 — Fix `templates/workflow-run.yml` for non-dogfood hosts

**Files:**

- Modify: `templates/workflow-run.yml`

- [ ] **Step 1: Read the current template to anchor the edit**

`templates/workflow-run.yml` lines 25-42 set up checkout → Python → pip install → claude CLI → orchestrator. The orchestrator step at line 42 runs `python scripts/orchestrator_runner.py --repo-root .`. On a non-dogfood host that file doesn't exist. We add a sibling checkout of the plugin before the orchestrator step.

- [ ] **Step 2: Apply the edit**

Insert a new checkout step right after `actions/setup-python@v6` (before `Install plugin deps`). Change the orchestrator run path to reference the sibling checkout.

After the edit, the steps block reads:

```yaml
steps:
  - uses: actions/checkout@v5
    with:
      fetch-depth: 0
  - uses: actions/setup-python@v6
    with:
      python-version: "3.11"
  - name: Check out engineering-docs-agent plugin
    # CCE-57: the host repo is not the plugin. Vendor the plugin's
    # scripts/ directory into the runner workspace at `.docs-agent-plugin`
    # so the orchestrator step can invoke it. `ref: main` until the plugin
    # cuts a versioned release; pin a tag/SHA here when one exists.
    uses: actions/checkout@v5
    with:
      repository: theoju/engineering-docs-agent
      ref: main
      path: .docs-agent-plugin
  - name: Install plugin deps
    run: pip install pyyaml jsonschema
  - name: Install Claude Code CLI
    run: npm install -g @anthropic-ai/claude-code
  - name: Run orchestrator
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    run: |
      python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

- [ ] **Step 3: Verify YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('templates/workflow-run.yml')); print('ok')"`
Expected: `ok` printed; no traceback.

- [ ] **Step 4: Commit**

```bash
git add templates/workflow-run.yml
git commit -m "feat(CCE-57): vendor plugin via sibling checkout in workflow-run template

The shipped workflow template assumed scripts/orchestrator_runner.py lived
at the host root; that is only true for the dogfood host. Add an explicit
checkout of theoju/engineering-docs-agent into .docs-agent-plugin/ and run
the orchestrator from that path so any non-dogfood host can use the
template without vendoring the plugin by hand.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: P2 — Add `detect_toolchain` to `setup_discover.py` (TDD)

**Files:**

- Modify: `scripts/setup_discover.py`
- Test: `tests/setup/test_setup_discover.py`

- [ ] **Step 1: Write the failing tests first**

Append to `tests/setup/test_setup_discover.py`:

```python
def test_detect_toolchain_bare_dir(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    out = setup_discover.detect_toolchain(tmp_path)
    assert out == {
        "node": False,
        "bun": False,
        "deno": False,
        "package_manager": None,
        "docusaurus_dep": False,
    }


def test_detect_toolchain_node_with_npm_lock(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "package-lock.json").write_text("{}")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["node"] is True
    assert out["package_manager"] == "npm"
    assert out["docusaurus_dep"] is False


def test_detect_toolchain_bun_lockfile_wins(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "bun.lockb").write_bytes(b"\x00")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["bun"] is True
    assert out["package_manager"] == "bun"


def test_detect_toolchain_docusaurus_dep(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    (tmp_path / "package.json").write_text(
        '{"name":"x","devDependencies":{"@docusaurus/core":"^3.0.0"}}'
    )
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["docusaurus_dep"] is True


def test_detect_toolchain_malformed_package_json_is_quiet(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    (tmp_path / "package.json").write_text("{not json")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["node"] is True
    assert out["docusaurus_dep"] is False


def test_detect_toolchain_deno(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    (tmp_path / "deno.json").write_text("{}")
    out = setup_discover.detect_toolchain(tmp_path)
    assert out["deno"] is True


def test_discover_surfaces_toolchain_block(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import setup_discover
    out = setup_discover.discover(tmp_path)
    assert "toolchain" in out
    assert isinstance(out["toolchain"], dict)
    assert set(out["toolchain"].keys()) == {
        "node", "bun", "deno", "package_manager", "docusaurus_dep"
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/setup/test_setup_discover.py -k toolchain -v`
Expected: 7 tests fail with `AttributeError: module 'setup_discover' has no attribute 'detect_toolchain'`.

- [ ] **Step 3: Implement `detect_toolchain` in `scripts/setup_discover.py`**

Insert this after `detect_openapi_hint` (around line 86) and before `detect_jira_hint`:

```python
def detect_toolchain(cwd: Path) -> dict:
    """Detect JavaScript / TypeScript toolchain hints.

    Returns a dict with:
      - node: package.json present
      - bun: bun.lockb present
      - deno: deno.json or deno.jsonc present
      - package_manager: "npm" | "yarn" | "pnpm" | "bun" | None
        (lockfile-derived; bun.lockb beats every npm-family lockfile)
      - docusaurus_dep: any @docusaurus/* in package.json deps/devDeps

    Malformed package.json is tolerated — docusaurus_dep falls back to False.
    """
    import json

    node = (cwd / "package.json").exists()
    bun = (cwd / "bun.lockb").exists()
    deno = (cwd / "deno.json").exists() or (cwd / "deno.jsonc").exists()

    package_manager: str | None = None
    if bun:
        package_manager = "bun"
    elif (cwd / "pnpm-lock.yaml").exists():
        package_manager = "pnpm"
    elif (cwd / "yarn.lock").exists():
        package_manager = "yarn"
    elif (cwd / "package-lock.json").exists():
        package_manager = "npm"

    docusaurus_dep = False
    if node:
        pj = cwd / "package.json"
        try:
            # 32KB cap — package.json files larger than that are pathological.
            text = pj.read_text(errors="ignore")[:32_768]
            data = json.loads(text)
            for block in ("dependencies", "devDependencies", "peerDependencies"):
                deps = data.get(block) or {}
                if any(k.startswith("@docusaurus/") for k in deps):
                    docusaurus_dep = True
                    break
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    return {
        "node": node,
        "bun": bun,
        "deno": deno,
        "package_manager": package_manager,
        "docusaurus_dep": docusaurus_dep,
    }
```

Then wire it into `discover()` — add this line right after the `openapi_hint` key in the out-dict:

```python
        "toolchain": detect_toolchain(cwd),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/setup/test_setup_discover.py -k toolchain -v`
Expected: 7 tests pass.

- [ ] **Step 5: Run full setup test suite for no regression**

Run: `python3 -m pytest tests/setup/ -v`
Expected: all tests pass (toolchain new + existing 13 unchanged).

- [ ] **Step 6: Commit**

```bash
git add scripts/setup_discover.py tests/setup/test_setup_discover.py
git commit -m "feat(CCE-57): detect Node/Bun/Deno toolchain in setup_discover

Adds detect_toolchain(cwd) returning {node,bun,deno,package_manager,
docusaurus_dep}. The setup skill's discovery summary now surfaces the
toolchain shape — required for the first JS/TS host (CCE-57). Existing
hosts gain a toolchain block in their discover() output; behavior of
detect_framework/detect_python/etc. is unchanged. Malformed package.json
is tolerated (docusaurus_dep falls back to False, no exception).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: P3 — Add `js_docusaurus` fixture and fixture-driven test

**Files:**

- Create: `tests/fixtures/setup_repos/js_docusaurus/package.json`
- Create: `tests/fixtures/setup_repos/js_docusaurus/package-lock.json`
- Create: `tests/fixtures/setup_repos/js_docusaurus/docusaurus.config.ts`
- Create: `tests/fixtures/setup_repos/js_docusaurus/docs/intro.md`
- Create: `tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml`
- Modify: `tests/setup/test_setup_discover.py`

- [ ] **Step 1: Write the failing fixture test**

Append to `tests/setup/test_setup_discover.py`:

```python
def test_js_docusaurus_fixture_full_discovery():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=FIX / "js_docusaurus",
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["framework"] == "docusaurus"
    assert out["source_dir"] == "docs"
    assert out["ci"] == "github_actions"
    assert out["python"]["detected"] is False
    assert out["toolchain"]["node"] is True
    assert out["toolchain"]["package_manager"] == "npm"
    assert out["toolchain"]["docusaurus_dep"] is True
    assert out["pages_publishable"] is False  # docusaurus is not auto-publishable
    # Docusaurus warning still fires
    assert any(
        w.get("code") == "docusaurus_v0.1_unsupported"
        for w in out.get("warnings", [])
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/setup/test_setup_discover.py::test_js_docusaurus_fixture_full_discovery -v`
Expected: FAIL — fixture directory does not exist.

- [ ] **Step 3: Create the fixture files**

`tests/fixtures/setup_repos/js_docusaurus/package.json`:

```json
{
  "name": "claude-code-self-assessment-fixture",
  "version": "0.0.0",
  "private": true,
  "devDependencies": {
    "@docusaurus/core": "^3.0.0",
    "@docusaurus/preset-classic": "^3.0.0"
  }
}
```

`tests/fixtures/setup_repos/js_docusaurus/package-lock.json`:

```json
{
  "name": "claude-code-self-assessment-fixture",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {}
}
```

`tests/fixtures/setup_repos/js_docusaurus/docusaurus.config.ts`:

```ts
import type { Config } from "@docusaurus/types";

const config: Config = {
  title: "Self-Assessment",
  url: "https://example.com",
  baseUrl: "/",
};

export default config;
```

`tests/fixtures/setup_repos/js_docusaurus/docs/intro.md`:

```markdown
# Intro

Stub docs page for the JS/TS host fixture.
```

`tests/fixtures/setup_repos/js_docusaurus/.github/workflows/ci.yml`:

```yaml
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      JIRA_BASE_URL: https://designitright.atlassian.net
    steps:
      - uses: actions/checkout@v5
      - run: echo stub
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/setup/test_setup_discover.py::test_js_docusaurus_fixture_full_discovery -v`
Expected: PASS.

- [ ] **Step 5: Run full setup test suite**

Run: `python3 -m pytest tests/setup/ -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/setup_repos/js_docusaurus tests/setup/test_setup_discover.py
git commit -m "test(CCE-57): add js_docusaurus fixture for JS/TS host discovery

Mirrors the shape of theoju/claude-code-self-assessment (CCE-57's target):
docusaurus.config.ts, package.json with @docusaurus/* devDeps,
package-lock.json (npm), a docs/ tree, and a github-actions workflow
declaring JIRA_BASE_URL. Pins discovery output: framework=docusaurus,
toolchain.node=True, package_manager=npm, docusaurus_dep=True,
python.detected=False, pages_publishable=False, docusaurus warning fires.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: P4 — Add `preflight_host.py` CLI (TDD)

**Files:**

- Create: `scripts/preflight_host.py`
- Create: `tests/setup/test_preflight_host.py`

- [ ] **Step 1: Write failing tests**

`tests/setup/test_preflight_host.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "preflight_host.py"
FIX = Path(__file__).parent.parent / "fixtures" / "setup_repos"


def test_preflight_json_mode_on_js_docusaurus():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(FIX / "js_docusaurus"), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out.keys()) >= {"discovery", "proposed_config", "secrets_checklist", "warnings"}
    assert out["discovery"]["framework"] == "docusaurus"
    assert out["discovery"]["toolchain"]["docusaurus_dep"] is True
    # Secrets the workflow needs
    names = {s["name"] for s in out["secrets_checklist"]}
    assert {"CLAUDE_CODE_OAUTH_TOKEN", "DOCS_AGENT_APP_ID", "DOCS_AGENT_APP_PRIVATE_KEY"} <= names


def test_preflight_text_mode_on_bare_repo():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(FIX / "bare"), "--format", "text"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    text = r.stdout
    assert "Discovery" in text
    assert "Secrets checklist" in text
    assert "framework: None" in text or "framework: none" in text.lower()


def test_preflight_emits_warning_when_no_framework():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(FIX / "bare"), "--format", "json"],
        capture_output=True,
        text=True,
    )
    out = json.loads(r.stdout)
    codes = {w["code"] for w in out["warnings"]}
    assert "no_docs_framework" in codes


def test_preflight_does_not_write_to_host(tmp_path):
    # Create a minimal host directory; ensure preflight leaves it untouched.
    (tmp_path / "README.md").write_text("# host")
    snapshot_before = sorted(p.name for p in tmp_path.iterdir())
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    snapshot_after = sorted(p.name for p in tmp_path.iterdir())
    assert snapshot_before == snapshot_after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v`
Expected: FAIL — `preflight_host.py` does not exist.

- [ ] **Step 3: Implement `scripts/preflight_host.py`**

```python
"""Read-only pre-flight readiness check for a host repo.

Runs discovery, prints the config the setup skill would write, the workflow
it would write, and a secrets checklist. Does not modify the host repo.

Usage:
    python scripts/preflight_host.py --repo-root /path/to/host [--format text|json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discover  # noqa: E402

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_TEMPLATE = _PLUGIN_ROOT / "templates" / "workflow-run.yml"


def proposed_config(discovery: dict) -> dict:
    """Compute the config dict the setup skill would write, without writing it."""
    framework = discovery.get("framework")
    source_dir = discovery.get("source_dir") or "docs"
    lens_paths = discovery.get("lens_paths") or {"core": source_dir}
    jira_hint = discovery.get("jira_hint") or {}
    return {
        "docs": {
            "framework": framework or "mkdocs",
            "source_dir": source_dir,
            "whats_new_file": f"{source_dir}/whats-new.md",
            "agent_editable_paths": [f"{source_dir}/**"],
            "lens_paths": lens_paths,
        },
        "sources": {
            "git": {"host": "github"},
            "jira": {
                "enabled": bool(jira_hint),
                "base_url": jira_hint.get("base_url") if jira_hint else None,
                "project_keys": [],
            },
        },
        "voice": {"sample_paths": ["CLAUDE.md", "README.md"]},
        "lint": {"tier1": "default"},
        "publishing": {
            "base_url": None,
            "build_workflow": "docs-agent-pages.yml" if discovery.get("pages_publishable") else None,
            "url_map_rule": "standard",
            "verify_timeout_seconds": 60,
        },
        "notifications": {
            "slack": {"enabled": False},
            "email": {"enabled": False},
        },
    }


def secrets_from_workflow(workflow_text: str) -> list[dict]:
    """Extract `secrets.X` references from the workflow template.

    Returns a sorted, de-duplicated list of {name, required} dicts. Required
    is True for the three workflow-blocking secrets, False for optional ones.
    """
    found = sorted(set(re.findall(r"secrets\.([A-Z_]+)", workflow_text)))
    required = {"CLAUDE_CODE_OAUTH_TOKEN", "DOCS_AGENT_APP_ID", "DOCS_AGENT_APP_PRIVATE_KEY"}
    # GITHUB_TOKEN is always injected by Actions; skip it from the checklist.
    found = [n for n in found if n != "GITHUB_TOKEN"]
    return [{"name": n, "required": n in required} for n in found]


def compute_warnings(discovery: dict) -> list[dict]:
    warnings = list(discovery.get("warnings", []))
    if not discovery.get("framework"):
        warnings.append({
            "code": "no_docs_framework",
            "message": (
                "No mkdocs.yml or docusaurus.config.* found at the repo root. "
                "Scaffold a docs site (mkdocs init, or `npx create-docusaurus@latest`) "
                "before running the setup skill."
            ),
        })
    if discovery.get("framework") == "docusaurus" and not discovery.get("pages_publishable"):
        warnings.append({
            "code": "pages_not_auto_scaffolded",
            "message": (
                "Docusaurus hosts are not auto-scaffolded for GitHub Pages. "
                "Set publishing.build_command (e.g. `npm run build`) and "
                "publishing.site_dir (e.g. `build`) in config.yml to enable."
            ),
        })
    if discovery.get("toolchain", {}).get("node") and not discovery.get("python", {}).get("detected"):
        warnings.append({
            "code": "node_only_host",
            "message": (
                "Node detected with no Python package. The orchestrator runs Python "
                "from .docs-agent-plugin/; this is expected for JS/TS hosts."
            ),
        })
    return warnings


def render_text(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("engineering-docs-agent host pre-flight")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Discovery")
    lines.append("-" * 60)
    for k, v in report["discovery"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Proposed config (.engineering-docs-agent/config.yml)")
    lines.append("-" * 60)
    lines.append(json.dumps(report["proposed_config"], indent=2))
    lines.append("")
    lines.append("Secrets checklist (set in repo Settings -> Secrets and variables -> Actions)")
    lines.append("-" * 60)
    for s in report["secrets_checklist"]:
        marker = "[required]" if s["required"] else "[optional]"
        lines.append(f"  [ ] {s['name']} {marker}")
    lines.append("")
    if report["warnings"]:
        lines.append("Warnings")
        lines.append("-" * 60)
        for w in report["warnings"]:
            lines.append(f"  - {w['code']}: {w['message']}")
        lines.append("")
    lines.append("Pre-flight read-only. No files modified.")
    return "\n".join(lines)


def build_report(repo_root: Path) -> dict:
    discovery = setup_discover.discover(repo_root)
    try:
        workflow_text = _WORKFLOW_TEMPLATE.read_text()
    except OSError:
        workflow_text = ""
    return {
        "discovery": discovery,
        "proposed_config": proposed_config(discovery),
        "secrets_checklist": secrets_from_workflow(workflow_text),
        "warnings": compute_warnings(discovery),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args()

    if not args.repo_root.exists():
        print(f"error: --repo-root does not exist: {args.repo_root}", file=sys.stderr)
        return 1

    report = build_report(args.repo_root)
    if args.format == "json":
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Run full setup suite for no regression**

Run: `python3 -m pytest tests/setup/ -v`
Expected: all pass.

- [ ] **Step 6: Manual smoke against the two fixtures**

Run:

```
python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/js_docusaurus --format text | head -40
python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/mkdocs_lensy --format text | head -40
```

Expected: both produce readable reports; js_docusaurus shows toolchain block; mkdocs_lensy does not warn `no_docs_framework`.

- [ ] **Step 7: Commit**

```bash
git add scripts/preflight_host.py tests/setup/test_preflight_host.py
git commit -m "feat(CCE-57): preflight_host CLI for host-side readiness reports

Read-only CLI run against any host repo: prints discovery, the config the
setup skill would write, and a secrets checklist scraped from the
workflow-run template. Surfaces three new warnings: no_docs_framework,
pages_not_auto_scaffolded (docusaurus), node_only_host. JSON --format json
output for machine consumption. Writes nothing to the host (asserted by a
snapshot test).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: P5 — Write the CCE-57 user runbook

**Files:**

- Create: `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md`

- [ ] **Step 1: Write the runbook**

`docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md`:

````markdown
# CCE-57 onboarding runbook — `theoju/claude-code-self-assessment`

This runbook executes the user-gated steps that the plugin-side prep (CCE-57 PR) cannot do for you. Follow it top-to-bottom. Each step lists what to run, what to expect, and what to do if it fails.

You will need: admin access to the target repo, the OAuth + App credentials from `docs/setup-guide.md` Part 1, and ~30 minutes uninterrupted.

## Prerequisites

- `claude --version` succeeds.
- The engineering-docs-agent plugin PR for CCE-57 is merged to `main` (so `templates/workflow-run.yml` and `scripts/preflight_host.py` exist).
- You have a local clone of `theoju/engineering-docs-agent` at `~/Projects/engineering-docs-agent` (paths below assume this).

## Step 1 — Clone the target

```bash
cd ~/Projects
git clone https://github.com/theoju/claude-code-self-assessment
cd claude-code-self-assessment
git checkout -b feat/CCE-57-bootstrap-docs-agent
```

**Expected:** clean clone, new branch checked out.

**If it fails:** check repo access and SSH config; this runbook assumes you can clone.

## Step 2 — Run preflight

```bash
python3 ~/Projects/engineering-docs-agent/scripts/preflight_host.py \
  --repo-root . \
  --format text
```

**Expected:** a Discovery block, a Proposed config block, a Secrets checklist with 5+ entries, and warnings. For this target the warnings will include `no_docs_framework` (no Docusaurus site yet) or `pages_not_auto_scaffolded` (if you've already scaffolded one).

**What to copy out:** the `Secrets checklist` rows. You will paste each into the GitHub UI in Step 7.

**If it fails:** confirm Python 3.11+ is on PATH; the script is stdlib-only — no pip install required.

## Step 3 — Install the plugin in the target

```bash
claude plugin marketplace add ~/Projects/engineering-docs-agent
claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace
```

**Expected:** install succeeds; `~/.claude/plugins/` contains the plugin.

**If it fails:** see `docs/setup-guide.md` Part 2.1.

## Step 4 — Run the setup skill

```bash
claude /engineering-docs-agent-setup
```

The skill prints discovered values (same as Step 2) and asks a small number of questions. For this target answer:

- **Notifications:** all `n` (Slack/email off; we'll opt in later if needed).
- **Voice samples:** accept default (`CLAUDE.md`, `README.md`).
- **Gap allowlist:** empty.
- **Tier-2 lint:** none (keep just Tier-1 default).
- **Glossary:** no.

**Expected outputs:**

- `.engineering-docs-agent/config.yml`
- `.engineering-docs-agent/state.json`
- `.github/workflows/docs-agent-nightly.yml` (or `docs-agent-run.yml`, depending on the skill's current naming)

The workflow file MUST contain a step named `Check out engineering-docs-agent plugin` (CCE-57 fix). If it doesn't, the skill is on an old plugin version — re-run Step 3.

**If it fails:** see `docs/setup-guide.md` Part 2.2.

## Step 5 — Register / reuse the GitHub App

Follow `docs/setup-guide.md` Part 1.2 to register the App if you don't already have one for this account. If you onboarded `theoju/engineering-docs-agent` previously, reuse the same App — no need to register a second one.

**Expected:** you have an App ID, a `.pem` private key file, and the App showing in `https://github.com/settings/apps`.

## Step 6 — Install the App on `claude-code-self-assessment`

Follow `docs/setup-guide.md` Part 2.3 — install the App, scope to this single repo.

**Verify:** `https://github.com/theoju/claude-code-self-assessment/settings/installations` shows your App.

## Step 7 — Set repo secrets

Use the checklist from Step 2's preflight output. For each row, in the GitHub UI:

1. Open `https://github.com/theoju/claude-code-self-assessment/settings/secrets/actions`.
2. Click **New repository secret**.
3. Paste name and value.

The five blocking secrets are:

- `CLAUDE_CODE_OAUTH_TOKEN` — from `claude setup-token` (starts with `sk-ant-oat`).
- `DOCS_AGENT_APP_ID` — App ID from Step 5.
- `DOCS_AGENT_APP_PRIVATE_KEY` — full contents of the `.pem` file (including BEGIN/END lines).
- `JIRA_API_TOKEN` — optional but recommended (Jira enrichment); see `docs/setup-guide.md` Part 1.3.
- `JIRA_EMAIL` — the Atlassian account email associated with the Jira token.

**Expected:** the Secrets list shows all five.

## Step 8 — Commit, push, open PR, smoke test

```bash
git add .engineering-docs-agent .github/workflows
git commit -m "feat: bootstrap engineering-docs-agent (CCE-57)"
git push -u origin feat/CCE-57-bootstrap-docs-agent
gh pr create --title "feat: bootstrap engineering-docs-agent (CCE-57)" \
  --body "Adds the docs-agent config + workflow per CCE-57."
```

Merge the PR via the GitHub UI (CCE-57 is a bootstrap, no required-check coverage yet). Then smoke the workflow:

```bash
gh workflow run docs-agent-nightly.yml \
  -R theoju/claude-code-self-assessment \
  -f reason="CCE-57 first-run smoke test"
gh run watch -R theoju/claude-code-self-assessment
```

**Expected (per `docs/setup-guide.md` Part 3.2):**

- A `docs-agent/<YYYY-MM-DD>T<HH>` branch appears.
- A docs-agent PR is open against `main`, authored by the App identity.
- `partial_reasons` block in the PR body lists `no_docs_framework` (expected — Docusaurus site not scaffolded yet) but does not list `jira_auth_missing` (proves Jira secrets wired correctly).

**If it fails:** check the workflow run log; cross-reference against `docs/setup-guide.md` Part 6 (Troubleshooting). The most common first-run failure is a typo in `DOCS_AGENT_APP_PRIVATE_KEY` (forgot to include the BEGIN/END lines).

## Optional next steps (after smoke test passes)

- **Scaffold Docusaurus** in the target (`npx create-docusaurus@latest`). After committing, re-run preflight — `no_docs_framework` warning should disappear and the next nightly will produce real content.
- **Branch protection** (`docs/setup-guide.md` Part 2.5). The host's test-check name will be Node-shaped (e.g. `test (node 20)`), not `pytest (3.11)`. Adjust accordingly.
- **actionlint workflow** (`docs/setup-guide.md` Part 5) — recommended for every host.

## Done

The host is onboarded when Step 8's smoke test produces a docs-agent PR with App identity. Move CCE-57 to "In Review" once the bootstrap PR is open on the target.
````

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md
git commit -m "docs(CCE-57): user runbook for claude-code-self-assessment onboarding

Step-by-step copy-paste sequence for the 8 user-gated steps the plugin
cannot perform: clone, preflight, plugin install, /engineering-docs-agent-setup,
GitHub App register/reuse, App install, repo secrets, commit+push+smoke.
Cross-references docs/setup-guide.md for the substantive sections (Part 1.2
App register, Part 2.3 App install, Part 2.5 branch protection, Part 6
troubleshooting). Expected outputs and recovery hints per step.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Update setup-skill docs

**Files:**

- Modify: `skills/engineering-docs-agent-setup/SKILL.md`

- [ ] **Step 1: Edit SKILL.md to mention toolchain block + plugin checkout**

In the "Procedure" section, in step 1 add a note about the new toolchain field. In step 6 add a note that the workflow contains the plugin checkout step (CCE-57). Diff target:

- After step 1 list item, append: "Output now includes a `toolchain` block ({node, bun, deno, package_manager, docusaurus_dep}) — surface this when displaying discovered values (CCE-57)."
- After step 6's `.github/workflows/docs-agent-run.yml` mention: "(CCE-57) The shipped workflow checks out `theoju/engineering-docs-agent` into `.docs-agent-plugin/` and runs the orchestrator from that path — do not delete the checkout step."

- [ ] **Step 2: Commit**

```bash
git add skills/engineering-docs-agent-setup/SKILL.md
git commit -m "docs(CCE-57): note toolchain block and plugin-checkout step in setup skill

Surfaces two CCE-57 deltas to the skill's procedure: discover() now emits a
toolchain block, and the shipped workflow template includes a sibling
checkout of the plugin repo. Both are observational notes — no behavior
change to the skill itself.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full test suite:**

```bash
python3 -m pytest -q
```

Expected: all tests pass; no regressions.

- [ ] **Lint the workflow template:**

```bash
python3 -c "import yaml; yaml.safe_load(open('templates/workflow-run.yml')); print('ok')"
```

Expected: `ok`.

- [ ] **Smoke preflight against both fixtures:**

```bash
python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/js_docusaurus --format json > /dev/null
python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/mkdocs_lensy --format json > /dev/null
```

Expected: both exit 0.

- [ ] **Branch ready for ship** — invoke `ship` skill.
