## Task 1: `resolve_window_cap`, the schema key, and their tests

Closes spec test-plan items **7** (schema round-trip) and **8** (the default is 10). Nothing is wired to the runner yet — this task's deliverable is a resolver and a schema property that a host can set without the config load failing.

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add constant near `:320`, add function after `resolve_deferral_stall_days` which ends at `:466`)
- Modify: `templates/config.schema.json` (the `run` block, `:205-229`)
- Create: `tests/orchestrator/test_window_cap.py`
- Modify: `tests/schemas/test_config_schema.py`

**Interfaces:**

- Consumes: `_run_cfg(config) -> dict` (`scripts/orchestrator_runner.py:398`) — the shared `run:` block accessor.
- Produces: `DEFAULT_WINDOW_PR_CAP: int = 10` and `resolve_window_cap(config: dict) -> int`. Task 2 calls `resolve_window_cap(config)` exactly once, inside `run`.

### Why the schema edit is not bookkeeping

`templates/config.schema.json`'s `run` block is `"additionalProperties": false` (`:207`). A key absent from the schema is a **hard config-load failure with exit 2**, not an ignored field: `jsonschema.validate` inside `load_config_validated` (`scripts/state_io.py:202`) raises `ConfigError`, and `run` turns that into `return 2` (`scripts/orchestrator_runner.py:2274`). A host that writes the advertised opt-out `window_pr_cap: 0` would get a config file that stops loading.

This is a live hazard, not a hypothetical: `run.deferral_stall_days` is documented as a host override and is **already** missing from this schema (filed as **CCE-184**). Do not fix CCE-184 here — this task adds `window_pr_cap` only.

- [ ] **Step 1: Write the failing resolver tests**

Create `tests/orchestrator/test_window_cap.py` with exactly this header and these four tests. The import shape is copied from `tests/orchestrator/test_deferral_skip.py:1-22`.

```python
# tests/orchestrator/test_window_cap.py
"""CCE-169: the pre-admission PR-count window cap.

The review window had no upper bound, so a stalled baseline widened by a day
every night and each run finished a smaller fraction of it. These tests pin the
cap itself (this file's first half) and the third-category routing that keeps a
capped PR out of the deferral machinery while still stopping the cursor at the
cap boundary (second half, added in Task 2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


# ---------------------------------------------------------------------------
# resolve_window_cap
# ---------------------------------------------------------------------------


def test_window_cap_defaults_to_ten():
    """The default is the whole point of CCE-169 and NOTHING else can catch it.

    Every `fake_source_collector.json` in the tree tops out at 3 PRs, and each
    helper that rewrites them keeps 3 — so `len(prs) > cap` is False for any
    default >= 3 and no end-to-end test can observe the value. An implementer
    who writes `int(run_cfg.get("window_pr_cap") or 0)` ships the rejected
    off-by-default alternative with every other test green.
    """
    assert orun.DEFAULT_WINDOW_PR_CAP == 10
    assert orun.resolve_window_cap({}) == 10
    assert orun.resolve_window_cap({"run": {}}) == 10


def test_window_cap_reads_the_config_key():
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 25}}) == 25


def test_window_cap_zero_is_unlimited():
    """`0` is the advertised opt-out, so it must survive as 0.

    This is why the resolver tests `val is None` and not truthiness: `or
    DEFAULT` would silently rewrite an explicit 0 back to 10.
    """
    assert orun.resolve_window_cap({"run": {"window_pr_cap": 0}}) == 0


def test_window_cap_tolerates_a_malformed_run_block():
    """`_run_cfg` exists because `config.get("run") or {}` raises
    AttributeError on `run: "nonsense"`. Mirror its siblings, do not reinvent.
    """
    assert orun.resolve_window_cap({"run": "nonsense"}) == 10
    assert orun.resolve_window_cap({"run": None}) == 10
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: 4 FAILED with `AttributeError: module 'orchestrator_runner' has no attribute 'DEFAULT_WINDOW_PR_CAP'` (and `resolve_window_cap`).

> If `pytest` produces mangled output, the `rtk` shell proxy is interfering. Prefix the command with `rtk proxy` to run it unfiltered.

- [ ] **Step 3: Add the constant**

In `scripts/orchestrator_runner.py`, immediately after line 320 (`DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3`), with a blank line either side and no comment — matching the shape of its neighbours:

```python
DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3

DEFAULT_WINDOW_PR_CAP = 10
```

- [ ] **Step 4: Add the resolver**

In `scripts/orchestrator_runner.py`, after `resolve_deferral_stall_days` (which ends at `:466` with `    return int(val)`) and before `def resolve_authoring_hard_cap(` — two blank lines between defs, matching house style:

```python
def resolve_window_cap(config: dict) -> int:
    """Resolve `run.window_pr_cap` (CCE-169). 0 = unlimited.

    The maximum number of merged PRs a single run admits, oldest-first. PRs
    beyond the cap are held for a later run: they enter `held_back`, so the
    CCE-151 cursor stops at the cap boundary, but they do NOT accrue deferral
    counts and are not exposed to the CCE-140 skip hatch, because the run never
    attempted them.

    Default-ON, unlike `citation_source_roots` and `lint.external_repos`. That
    is deliberate: every CCE-169 incident happened on a host that had configured
    nothing, and an opt-in guard against an unrecoverable failure is discovered
    by having the failure. A cap set too tight is a visible nightly reason an
    operator raises in one edit; a cap set too loose is a silent stall that cost
    113 PRs of documentation on ADIS.
    """
    run_cfg = _run_cfg(config)
    val = run_cfg.get("window_pr_cap")
    if val is None:
        return DEFAULT_WINDOW_PR_CAP
    return int(val)
```

**Mirror this idiom exactly; do not invent one.** `_run_cfg(config)`, never `config.get("run") or {}`. `if val is None:`, never a truthiness test and never `or DEFAULT` — that is what lets an explicit `0` survive. `int(val)` unguarded — the JSON-schema layer is what rejects wrong types for real hosts, and only raw-dict unit tests reach here otherwise.

- [ ] **Step 5: Run the resolver tests to verify they pass**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/orchestrator/test_window_cap.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Write the failing schema round-trip test**

Append to `tests/schemas/test_config_schema.py`. The file already imports `json`, `yaml`, `Path`, `validate`, `ValidationError`, `pytest` and binds `SCHEMA` at module level — use them; do not add imports.

```python
def test_run_window_pr_cap_accepted():
    """CCE-169. `run` is additionalProperties: false, so a key missing from the
    schema is a hard load failure with exit 2, not an ignored field — and the
    bare host is the one case that omission spares, which is what would keep the
    gap invisible until the night an operator reaches for the opt-out.

    Assert on a SUCCESSFUL load. A test that counts ValidationErrors passes
    whether or not the property exists.
    """
    run = SCHEMA["properties"]["run"]
    validate({"window_pr_cap": 10}, run)
    validate({"window_pr_cap": 0}, run)


def test_run_window_pr_cap_rejects_negative():
    run = SCHEMA["properties"]["run"]
    with pytest.raises(ValidationError):
        validate({"window_pr_cap": -1}, run)
```

- [ ] **Step 7: Run it to verify it fails**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py -k window_pr_cap -v
```

Expected: `test_run_window_pr_cap_accepted` FAILS with `ValidationError: Additional properties are not allowed ('window_pr_cap' was unexpected)`. (`test_run_window_pr_cap_rejects_negative` passes vacuously — for the wrong reason, which is exactly why the accepted-case test is the one that matters.)

- [ ] **Step 8: Add the schema property**

In `templates/config.schema.json`, inside `properties.run.properties`, after the `authoring_hard_cap_seconds` entry (which ends at `:226`), adding a comma to the preceding entry's closing brace:

```json
        "window_pr_cap": {
          "type": "integer",
          "minimum": 0,
          "description": "CCE-169: maximum merged PRs a single run admits, oldest-first. PRs beyond the cap are held for a later run: they are excluded from the advance cursor so the baseline stops at the cap boundary, and they do NOT accrue deferral counts, because they were never attempted. Default 10. 0 = unlimited, restoring the pre-CCE-169 unbounded window."
        }
```

- [ ] **Step 9: Run both test files to verify green**

```bash
cd ~/Projects/eda-cce181 && python3 -m pytest tests/schemas/test_config_schema.py tests/orchestrator/test_window_cap.py -v
```

Expected: all pass, including the two new schema cases.

- [ ] **Step 10: Commit**

```bash
cd ~/Projects/eda-cce181
git add scripts/orchestrator_runner.py templates/config.schema.json \
        tests/orchestrator/test_window_cap.py tests/schemas/test_config_schema.py
git commit -m "$(cat <<'EOF'
feat(orchestrator): resolve_window_cap + run.window_pr_cap schema key — CCE-169

The resolver and its config key, not yet wired to the admission path.

The default (10) gets its own direct unit assertion because nothing else can
catch it: every fake_source_collector.json in the tree tops out at 3 PRs, so
`len(prs) > cap` is False for any default >= 3 and no end-to-end test can
observe the value. An implementer writing `or 0` would ship the rejected
off-by-default alternative with every other test green.

The schema edit is load-bearing, not bookkeeping. `run` is
additionalProperties: false, so omitting the key makes `window_pr_cap: 0` --
the advertised opt-out -- hard-fail config load with exit 2. The bare host is
the one case that omission spares, which is what would keep the gap invisible
until an operator reached for the opt-out. Asserts on a successful load, never
on a ValidationError count.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

