# tests/agents/test_source_collector_total_budget.py
"""CCE-198: the contract must state a TOTAL payload budget and a FLOOR.

The 2026-09-30 incident, in one line: the collector emitted 139 PRs with
`body: null` and a payload of 56,938 characters -- 36% of the measured
~160,000-character ceiling, with roughly 100,000 characters unused.

Nothing failed. The agent shed three times, and the ordering of what it saw
rules out the obvious explanation: the rung it measured at 78,077 characters
carried NO "Output too large" notice and it shed anyway, while the rung at
56,955 carried one and it stopped. So the harness notice was not the quantity
being compared.

What the contract gave it, before this file:

  * `1,000 characters` stated four times, always PER FIELD;
  * "your output ceiling" invoked three times with NO NUMBER attached;
  * three warnings that an over-long payload loses the ENTIRE run;
  * an explicit asymmetric preference, "A bounded `body` is worth more than a
    complete one";
  * no total, no PR-count bound, and no floor.

That instruction set is monotone: smaller is always safer and nothing says
where to stop. The agent had to invent both its target and its stopping rule.

And its first shed was FORCED, not timid. CCE-177 calibrated the 1,000-char
figure against the widest window then observed -- 20 PRs, ~50% of ceiling. This
window held 139. Exact compliance with the per-field rule yields 224,414
characters, 140% of the ceiling. The premise the budget rests on was violated
sevenfold, and the contract never said the premise existed.

A floor alone would have been WORSE than nothing: "do not shed below 200
characters" is not evaluable by an agent that was never told the ceiling, and
Step 6 closes with "If any check fails, return to the missing step", so an
unsatisfiable check churns. The floor is only meaningful once the total is a
number the agent can measure against. Both land here together, or neither.

RELATIONSHIP TO `test_source_collector_output_budget.py` (CCE-177): that file
pins the PER-FIELD budget and extracts its number with
`re.findall(r"at most ([\\d,]+) characters in total", passage)` under
`assert len(found) == 1`, per passage, where a passage is a whole `### Step N`
section. This file's subject must therefore live OUTSIDE any step section and
must not use that phrasing -- `test_the_new_wording_cannot_break_cce177` pins
exactly that, so a future reword cannot break the older file by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
AGENT_MD = _ROOT / "agents" / "source-collector.md"

#: The whole-payload ceiling the contract must state.
TOTAL = 120_000

#: The minimum `body` text the contract must refuse to go below while the
#: measured total is under TOTAL.
FLOOR = 200

#: CCE-177's measured output ceiling. TOTAL must sit beneath it with headroom.
MEASURED_CEILING = 160_000

#: CCE-177's per-field bound, which this file must NOT change.
PER_FIELD = 1_000


@pytest.fixture(scope="module")
def body() -> str:
    return AGENT_MD.read_text()


@pytest.fixture(scope="module")
def section(body: str) -> str:
    """The `## Payload budget` section, up to the next top-level heading.

    Returns "" rather than raising when it is gone, so the named tests below
    report which property went missing instead of erroring identically.
    """
    m = re.search(r"^## Payload budget\b", body, re.M)
    if not m:
        return ""
    rest = body[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _flat(text: str) -> str:
    """Collapse whitespace AND drop markdown emphasis.

    Both are necessary. The contract wraps prose, so a phrase can straddle a
    newline; and it bolds the load-bearing words, so `does **not** scale`
    defeats a literal `"does not"` check. A test about what the contract SAYS
    must not be defeated by how it is typeset.
    """
    return re.sub(r"\s+", " ", text.replace("*", "")).strip()


# --------------------------------------------------------------------------
# The total exists, is a number, and leaves headroom
# --------------------------------------------------------------------------


def test_the_payload_budget_section_exists(section: str):
    """The bluntest failure. Without this section the agent is back to
    inventing its own target against an unnamed ceiling."""
    assert section, (
        "`## Payload budget` is gone from agents/source-collector.md. It is "
        "the only place the whole-payload ceiling is stated as a number; "
        "without it every 'your output ceiling' warning in the contract is "
        "attached to a quantity the agent cannot evaluate."
    )


def test_the_total_is_stated_as_a_number(section: str):
    """The actually-missing input in the 09-30 incident.

    Not 'keep it small', not 'your output ceiling' -- a figure.
    """
    found = re.findall(r"ceiling of ([\d,]+) characters", _flat(section))
    assert found, (
        "the section does not state the whole-payload ceiling as "
        "'ceiling of N characters'. An unquantified ceiling is what the agent "
        "had on 2026-09-30, and it shed to 36% of the real one."
    )
    assert {int(f.replace(",", "")) for f in found} == {TOTAL}, found


def test_the_total_leaves_headroom_under_the_measured_ceiling(section: str):
    """A budget equal to the ceiling is not a budget.

    The ceiling is approximate and measured, so the stated total must sit
    below it by a margin the contract names as deliberate.
    """
    flat = _flat(section)
    assert TOTAL < MEASURED_CEILING, (TOTAL, MEASURED_CEILING)
    assert str(f"{MEASURED_CEILING:,}") in flat, (
        "the section does not name the measured output ceiling, so a reader "
        "cannot tell the stated total is a deliberate fraction of it rather "
        "than the ceiling itself"
    )
    assert "headroom" in flat, (
        "the gap between the stated total and the measured ceiling is not "
        "identified as deliberate headroom, so a future edit is free to close it"
    )


def test_the_agent_is_told_to_measure_rather_than_estimate(section: str):
    """The agent on 09-30 did measure, with `wc -c`, at every rung -- what it
    lacked was a number to compare against. Keep the measurement mandated
    anyway: the total is unusable without it, and an estimate reintroduces
    exactly the guesswork this ticket removes."""
    flat = _flat(section)
    assert "wc -c" in flat, "the section does not name a concrete way to measure"
    assert "do not estimate" in flat.lower() or "rather than estimating" in flat.lower()


# --------------------------------------------------------------------------
# The floor, and the instruction not to trim a payload that already fits
# --------------------------------------------------------------------------


def test_the_floor_is_stated_as_a_number(section: str):
    """`body: null` across 139 PRs is the thing being forbidden."""
    found = re.findall(r"at least ([\d,]+) characters", _flat(section))
    assert found, "the section states no numeric floor for `body`"
    assert {int(f.replace(",", "")) for f in found} == {FLOOR}, found


def test_the_floor_sits_below_the_per_field_bound(section: str):
    """Internal consistency: a floor above the per-field cap is unsatisfiable,
    and would make every run fail the Step 6 gate it cannot pass."""
    assert FLOOR < PER_FIELD, (FLOOR, PER_FIELD)


def test_the_floor_names_the_two_fields_that_were_deleted(section: str):
    """`labels` and `jira_keys` were `del`'d outright at the third rung, so a
    floor phrased only about `body` would not have prevented the incident."""
    flat = _flat(section)
    assert "`labels`" in flat and "`jira_keys`" in flat, flat[:400]
    assert "`body: null`" in flat, (
        "the section does not forbid the exact shape the 09-30 payload "
        "carried for all 139 PRs"
    )


def test_a_payload_that_fits_must_not_be_trimmed_further(section: str):
    """The precise defect. 56,938 characters was already comfortably inside
    the ceiling and the agent trimmed anyway, twice.

    The contract must make 'it fits' terminal, and must say why trimming past
    that point is not merely wasteful but destructive -- the orchestrator
    advances its baseline over PRs it was given, so emptied content is gone
    for good rather than deferred.
    """
    flat = _flat(section)
    assert "do not trim further" in flat.lower(), (
        "the section does not tell the agent to stop once the payload fits"
    )
    assert "never recover" in flat.lower() or "can never recover" in flat.lower(), (
        "the section does not state that content shed below the ceiling is "
        "lost permanently rather than deferred, which is the fact that makes "
        "over-shedding worse than over-shooting"
    )


# --------------------------------------------------------------------------
# The escape hatch, without which the floor is unsatisfiable at scale
# --------------------------------------------------------------------------


def test_over_budget_sheds_pr_count_not_field_content(section: str):
    """At 139 PRs no non-zero per-field cap fits, so an absolute floor with no
    escape hatch tells the agent both 'never empty a body' and 'an over-long
    payload loses the run' with no legal move left.

    Shedding PR COUNT is the legal move, and it is also the recoverable one:
    the orchestrator can observe that the window held more PRs than were
    returned (CCE-192), whereas a PR present with no content is
    indistinguishable from one that genuinely had none.
    """
    flat = _flat(section)
    assert re.search(r"shed whole PRs", flat), (
        "the section gives no escape hatch for a window too large for the "
        "floor; the floor is then unsatisfiable and Step 6 churns on it"
    )
    assert "oldest" in flat, "the shed order is unspecified, so it is arbitrary"
    assert "recoverable" in flat, (
        "the section does not say why shedding count beats emptying fields"
    )


def test_the_per_field_bound_is_declared_not_to_scale(section: str):
    """The unstated premise that caused the incident.

    CCE-177 calibrated 1,000 characters against a ~20-PR window. Nothing said
    so, so a 139-PR window inherited a budget that implies 140% of the
    ceiling, and the agent discovered the conflict with no guidance on how to
    resolve it.
    """
    flat = _flat(section)
    assert re.search(r"\b20 PRs\b", flat), (
        "the section does not state the window size the per-field bound was "
        "calibrated against, so its inapplicability at scale stays invisible"
    )
    assert "does not" in flat and "scale" in flat, (
        "the section does not say the per-field bound fails to scale with window size"
    )


# --------------------------------------------------------------------------
# Reachability: an agent reading only a step must still be routed here
# --------------------------------------------------------------------------


def test_step_3_routes_the_reader_to_the_total_budget(body: str):
    """Step 3 is where the agent learns the per-field bound. If that is the
    only budget it sees there, it will apply it and stop -- which is precisely
    what happened."""
    m = re.search(r"^### Step 3\b", body, re.M)
    assert m
    rest = body[m.end() :]
    nxt = re.search(r"^### Step ", rest, re.M)
    step3 = _flat(rest[: nxt.start()] if nxt else rest)
    assert "§Payload budget" in step3, (
        "Step 3 does not point at the whole-payload budget, so an agent that "
        "reads the per-field bound there has no reason to look for a second one"
    )
    assert "per field" in step3, (
        "Step 3 does not label its own bound as per-field, so it reads as the "
        "only budget"
    )


def test_step_6_gates_on_the_measured_total(body: str):
    """Step 6 is the pre-emit checklist -- the last point at which an
    over-shed payload can be caught before it is emitted."""
    m = re.search(r"^### Step 6\b", body, re.M)
    assert m
    rest = body[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    step6 = _flat(rest[: nxt.start()] if nxt else rest)
    assert f"{TOTAL:,} characters or fewer" in step6, (
        "Step 6 does not check the measured total against the stated ceiling"
    )
    assert f"{FLOOR} characters of `body`" in step6, (
        "Step 6 does not check the floor, so an over-shed payload passes the "
        "last gate before emission"
    )


# --------------------------------------------------------------------------
# The guard that encodes what this change had to work around
# --------------------------------------------------------------------------


def test_the_new_wording_cannot_break_cce177(body: str, section: str):
    """CCE-177's extraction is fragile in two specific ways, and both would
    fail as a DELETION report rather than as a wording complaint.

    1. `_total` finds `at most N characters in total` per `### Step N` section
       and asserts exactly one match. A second such phrase inside Step 3 or
       Step 5 fails it.
    2. The Step 6 passage is isolated by filtering checklist bullets for the
       literal ``prs[].body`` under `len(matching) == 1`. A second bullet
       naming it yields `step6 = ""`, which fails five of that file's tests
       with "the passage is gone".

    Pinned here because a future reword of this section or of the Step 6 check
    is the likely trigger, and the resulting failure names the wrong file.
    """
    assert "characters in total" not in section, (
        "`## Payload budget` uses CCE-177's extraction phrasing. It is a "
        "top-level section today so it is out of reach, but moving it under a "
        "`### Step N` heading would then break "
        "test_source_collector_output_budget.py as a false deletion report."
    )

    m = re.search(r"^### Step 6\b", body, re.M)
    rest = body[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    step6 = rest[: nxt.start()] if nxt else rest
    bullets = re.split(r"\n(?=- )", step6)
    naming = [b for b in bullets if "`prs[].body`" in b]
    assert len(naming) == 1, (
        f"{len(naming)} Step 6 checklist bullets name `prs[].body`; CCE-177's "
        f"fixture requires exactly one and silently yields an empty passage "
        f"otherwise. The new measurement bullet must say `body`, not "
        f"`prs[].body`."
    )
