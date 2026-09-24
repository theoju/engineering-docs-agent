# tests/agents/test_source_collector_output_budget.py
"""CCE-177 (change A): source-collector's per-field byte budget must be
stated in the contract, and all three passages must state the SAME number.

A is the load-bearing half of CCE-177. B — `_detect_output_token_limit_split`
— only fires where `DOCS_AGENT_DEBUG_DIR` is set and an event stream exists;
on the documented bare-host default there are no events and B never runs. The
byte budget is the only thing that keeps the output ceiling from being crossed
on *every* host, in either output mode. Deleting these three passages was, at
the time this file was written, invisible to the whole suite.

The original defect was not a missing number but three passages DISAGREEING:
an earlier draft told the agent to "cut at N characters, append
`…[truncated]`" — which yields an N+12 value — while the Step 6 checklist
asked whether the value was "at most N characters, with `…[truncated]`
appended", a condition no correctly-truncated value can satisfy. Step 6 closes
with "If any check fails, return to the missing step", so a model reading it as
a gate would churn.

So these tests extract the number from each passage INDEPENDENTLY and assert
the passages agree, rather than asserting a literal three times. Changing the
budget in two places out of three fails here; changing it in all three is a
deliberate edit and passes.

`tests/agents/test_schema_md_sync.py` cannot catch any of this: it compares
only the `## Output schema (canonical)` fenced block, and the budget is an
instruction, not a schema constraint (see the spec's "Rejected" section for
why `maxLength` would be strictly worse).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
AGENT_MD = _ROOT / "agents" / "source-collector.md"

#: The truncation marker the contract mandates. Its own length is what makes
#: the budget marker-INCLUSIVE arithmetic check meaningful.
MARKER = "…[truncated]"


def _sections(body: str) -> dict[str, str]:
    """Split the `## Procedure` steps into `{"Step 3": "...", ...}`.

    Keyed by step number only, so rewording a heading's descriptive tail
    (`— Pull per-PR metadata`) does not break the lookup.
    """
    out: dict[str, str] = {}
    heads = list(re.finditer(r"^### Step ([0-9.]+)\b.*$", body, re.M))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out[f"Step {m.group(1)}"] = body[m.start() : end]
    return out


def _flat(text: str) -> str:
    """Collapse whitespace so a passage reads the same however it is wrapped.

    Necessary, not cosmetic: Step 5 wraps "at most" across a newline in the
    file as shipped, so every regex below would miss it unwrapped.
    """
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(scope="module")
def body() -> str:
    return AGENT_MD.read_text()


@pytest.fixture(scope="module")
def passages(body: str) -> dict[str, str]:
    """The three passages that must agree, each whitespace-normalized.

    Step 3 and Step 5 are whole sections. Step 6 is the single pre-emit
    checklist bullet that carries the budget — isolated so an unrelated
    checklist bullet gaining a number cannot satisfy this file.

    A missing passage yields "" rather than raising. The fixture deliberately
    does not assert: an assertion here turns one deleted passage into fifteen
    identical errors, and the named tests below say which passage went and
    what it was supposed to carry.
    """
    sections = _sections(body)

    bullets = re.split(r"\n(?=- )", sections.get("Step 6", ""))
    matching = [b for b in bullets if "`prs[].body`" in b]
    # Cut at the blank line so the bullet does not absorb the trailing
    # "If any check fails..." paragraph.
    step6 = matching[0].split("\n\n")[0] if len(matching) == 1 else ""

    return {
        "Step 3": _flat(sections.get("Step 3", "")),
        "Step 5": _flat(sections.get("Step 5", "")),
        "Step 6 checklist": _flat(step6),
    }


def _total(passage: str, label: str) -> int:
    """The budget this passage states, as an int.

    One uniform regex across all three passages: the point of this file is
    that they agree, and an extractor with a per-passage special case could
    paper over a disagreement.
    """
    found = re.findall(r"at most ([\d,]+) characters in total", passage)
    assert len(found) == 1, (
        f"{label}: expected exactly one 'at most N characters in total' "
        f"statement of the byte budget, found {found}. CCE-177 change A is "
        f"the only protection on hosts where DOCS_AGENT_DEBUG_DIR is unset."
    )
    return int(found[0].replace(",", ""))


# --------------------------------------------------------------------------
# The budget is stated at all — once per passage
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["Step 3", "Step 5", "Step 6 checklist"])
def test_the_passage_exists_at_all(passages: dict[str, str], label: str):
    """The bluntest failure, named so a deletion says which passage went."""
    assert passages[label], (
        f"{label} is gone from agents/source-collector.md. It is one of "
        f"CCE-177 change A's three edits; on a host with "
        f"DOCS_AGENT_DEBUG_DIR unset it is the only protection against the "
        f"output ceiling, because the detector has no event stream to read."
    )


@pytest.mark.parametrize("label", ["Step 3", "Step 5", "Step 6 checklist"])
def test_each_passage_states_a_byte_budget(passages: dict[str, str], label: str):
    """Deleting any one of change A's three edits fails here."""
    assert _total(passages[label], label) > 0


def test_step_3_binds_the_budget_to_prs_body(passages: dict[str, str]):
    """A budget stated about nothing in particular is not a budget."""
    assert "`body`" in passages["Step 3"]


def test_step_5_binds_the_budget_to_jira_description(passages: dict[str, str]):
    assert "`description`" in passages["Step 5"]


def test_the_step_6_checklist_covers_both_fields(passages: dict[str, str]):
    step6 = passages["Step 6 checklist"]
    assert "`prs[].body`" in step6
    assert "`jira_issues[].description`" in step6


# --------------------------------------------------------------------------
# ...and all three state the SAME number
# --------------------------------------------------------------------------


def test_all_three_passages_state_the_same_total(passages: dict[str, str]):
    """The headline assertion, and the one that reproduces the original bug.

    Extracted per passage and compared to each other — never to a literal —
    so an edit that changes the budget in two places out of three is caught
    whichever two they are.
    """
    totals = {label: _total(text, label) for label, text in passages.items()}
    assert len(set(totals.values())) == 1, (
        f"the byte budget disagrees across passages: {totals}. Step 3, Step 5 "
        f"and the Step 6 pre-emit checklist must state one number; a checklist "
        f"that asks for a total the authoring steps do not produce is a gate "
        f"the agent can never pass."
    )


def test_the_agent_still_says_1000_somewhere(passages: dict[str, str]):
    """One literal, asserted once, so the equality test above cannot pass
    vacuously on a budget silently relaxed to 100,000 in all three places.

    Deliberately weak: it pins the shipped value without duplicating it three
    times. The spec's measurement — a 1,000-char cap replays the 09-23 window
    at ~50% of the measured ~160,000-char ceiling, a 2,000-char cap at ~86% —
    is what justifies the number.
    """
    assert _total(passages["Step 3"], "Step 3") == 1000


# --------------------------------------------------------------------------
# ...and they state it as marker-INCLUSIVE
# --------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["Step 3", "Step 5", "Step 6 checklist"])
def test_the_budget_is_stated_as_marker_inclusive(passages: dict[str, str], label: str):
    """A cut value is EXACTLY the total, not total + len(marker).

    This is the half the first draft got wrong. Each passage must say so in
    its own text: the number the agent cuts to and the number the checklist
    measures have to be the same number.
    """
    passage = passages[label]
    total = _total(passage, label)
    assert MARKER in passage, f"{label}: the truncation marker is not named"
    assert f"exactly {total:,} characters" in passage, (
        f"{label}: does not state that a cut value is exactly {total:,} "
        f"characters. If the marker is appended ON TOP of the budget, a "
        f"truncated value is {total + len(MARKER):,} long and the Step 6 "
        f"check can never pass."
    )


@pytest.mark.parametrize(
    "label, cut_re, marker_re",
    [
        ("Step 3", r"cut the text at ([\d,]+) characters", r"\(([\d,]+) characters\)"),
        ("Step 5", r"cut the text at ([\d,]+) characters", r"\(([\d,]+) characters\)"),
        ("Step 6 checklist", r"\(([\d,]+) of text plus", r"([\d,]+)-character marker"),
    ],
)
def test_the_cut_arithmetic_adds_up_to_the_total(
    passages: dict[str, str], label: str, cut_re: str, marker_re: str
):
    """text-cut length + marker length == the stated total, per passage.

    The wording differs between the authoring steps ("cut the text at 988
    characters and append `…[truncated]` (12 characters)") and the checklist
    ("988 of text plus the 12-character marker"), so the extraction differs —
    but the arithmetic each passage asserts is identical, and the marker
    length must match the marker's real length.
    """
    passage = passages[label]
    total = _total(passage, label)

    cut = re.findall(cut_re, passage)
    assert len(cut) == 1, f"{label}: no single text-cut length found, got {cut}"
    marker_len = re.findall(marker_re, passage)
    assert len(marker_len) == 1, (
        f"{label}: no single marker length found, got {marker_len}"
    )

    cut_n = int(cut[0].replace(",", ""))
    marker_n = int(marker_len[0].replace(",", ""))

    assert marker_n == len(MARKER), (
        f"{label}: claims the marker is {marker_n} characters; "
        f"{MARKER!r} is {len(MARKER)}"
    )
    assert cut_n + marker_n == total, (
        f"{label}: {cut_n} + {marker_n} != {total} — the contract's own "
        f"arithmetic does not close, so a model following it emits a value "
        f"the checklist then rejects"
    )


def test_the_step_3_metadata_line_agrees_with_the_budget_it_introduces(
    body: str, passages: dict[str, str]
):
    """Step 3 names the bound twice: once inline in the field list
    ("`body` (bounded to N characters)") and once in the paragraph below.

    A fourth statement of the same number, pinned because it is the one most
    easily missed when the budget is retuned — it does not match any of the
    regexes above.
    """
    section = _flat(_sections(body)["Step 3"])
    inline = re.findall(r"`body` \(bounded to ([\d,]+) characters\)", section)
    assert len(inline) == 1, f"Step 3's inline `body` bound is missing: {inline}"
    assert int(inline[0].replace(",", "")) == _total(passages["Step 3"], "Step 3")
