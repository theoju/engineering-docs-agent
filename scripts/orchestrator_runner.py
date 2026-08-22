"""Orchestrator runner. Used by GitHub Actions and integration tests.

Calls subagents via the Claude Code CLI in production. In `--dry-run-subagents`
mode (used in tests), reads canned JSON outputs from a fixture directory
instead of invoking Claude.
"""

from __future__ import annotations
import argparse, fnmatch, hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
import yaml

from gh_client import GhClient
from build_poller import resolve_build_trigger
from state_io import (
    ConfigError,
    StateError,
    add_partial,
    cleanup_empty_parents,
    load_config_validated,
    load_state_validated,
    load_voice_samples,
    merge_skipped_pr_records,
    resolve_lens,
    save_current_run,
    save_persistent_state,
)
from stderr_emit import _OBSERVABILITY_FLUSH, _redact_credentials, emit_log


def detect_repo(repo_root: Path) -> dict[str, str]:
    """Detect GitHub owner/name from git remote or GITHUB_REPOSITORY env."""
    if env := os.environ.get("GITHUB_REPOSITORY"):
        if "/" in env:
            owner, name = env.split("/", 1)
            return {"owner": owner, "name": name}
    r = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    url = r.stdout.strip()
    # Parse github.com/<owner>/<name> from ssh or https URLs.
    import re

    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if m:
        return {"owner": m.group(1), "name": m.group(2)}
    return {"owner": "unknown", "name": "unknown"}


def load_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text()) or {}


def load_json(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_AGENT_ALLOWED_TOOLS: tuple[str, ...] = ("Bash", "Read", "Write", "Edit", "WebFetch")
_AGENTS_DIR: Path = Path(__file__).resolve().parent.parent / "agents"
_AGENT_TOOLS_CACHE: dict[str, tuple[str, ...] | None] = {}


def _load_agent_allowed_tools(name: str) -> tuple[str, ...] | None:
    """Parse `tools:` YAML frontmatter from agents/<name>.md.

    Returns a tuple of tool names if the agent declares them, or None
    if the agent has no `tools:` frontmatter (caller should omit
    --allowedTools entirely for that case).

    Result is cached per agent name; clear _AGENT_TOOLS_CACHE in tests
    that swap _AGENTS_DIR.
    """
    if name in _AGENT_TOOLS_CACHE:
        return _AGENT_TOOLS_CACHE[name]

    agent_path = _AGENTS_DIR / f"{name}.md"
    if not agent_path.exists():
        _AGENT_TOOLS_CACHE[name] = None
        return None

    text = agent_path.read_text()
    # Frontmatter is delimited by lines that are exactly "---".
    if text.startswith("---\n"):
        # split on the first "\n---\n" after the opening "---\n"
        body_split = text[4:].split("\n---\n", 1)
        if len(body_split) == 2:
            fm_text = body_split[0]
        else:
            _AGENT_TOOLS_CACHE[name] = None
            return None
    else:
        _AGENT_TOOLS_CACHE[name] = None
        return None

    fm = yaml.safe_load(fm_text) or {}
    tools = fm.get("tools")
    if tools is None:
        _AGENT_TOOLS_CACHE[name] = None
        return None
    if not isinstance(tools, list):
        # Malformed: surface clearly rather than fall back to the union.
        raise ValueError(
            f"agent {name}: 'tools' frontmatter must be a YAML list; got {type(tools).__name__}"
        )

    result = tuple(str(t) for t in tools)
    _AGENT_TOOLS_CACHE[name] = result
    return result


_STDERR_TRUNCATE = 300
_EXECUTION_FRAMING = (
    "You are running in production as part of the engineering-docs-agent "
    "orchestrator pipeline.\n\n"
    "Your inputs (JSON) are below. Execute the Job defined in your system "
    "prompt using these inputs. Return ONLY a JSON object matching your "
    "output contract — no prose, no markdown fences, no commentary, no "
    "clarifying questions.\n\n"
    "<inputs>\n{payload}\n</inputs>\n"
)


def _rescue_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from prose-contaminated
    text. Returns the parsed dict on success, None otherwise.

    Defense in depth for CCE-15. With --setting-sources project,local
    (Task 1) the SessionStart-hook contamination pathway is closed via
    user-settings exclusion, but other contamination
    patterns may exist (CCE-14 Run 4 was an "★ Insight" preamble
    injected by the explanatory-output-style plugin). When strict
    json.loads on the dispatch output fails, callers can fall through
    to this rescue.

    Algorithm: find the first '{', scan forward tracking brace depth
    while honoring JSON string state (open quote, escaped quote skip).
    When depth returns to 0, attempt json.loads on the slice.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# CCE-55: whole-string match for the most common LLM contamination —
# the model wraps its JSON in a markdown code fence despite explicit
# "no fences" instructions in both the agent contract and the
# orchestrator's execution-framing prompt. Observed rate on the
# 2026-05-29 docs-agent-nightly run that produced PR #69: ~19%
# (3 of 16 schema-bearing dispatches). The fence content is byte-equal
# to the JSON the model intended, so stripping here lets the strict
# json.loads in dispatch_subagent succeed without triggering the
# rescue path's prose_contamination_rescued partial reason.
_FENCE_RE = re.compile(
    r"\A\s*```[A-Za-z0-9]*\s*\n(.*)\n```\s*\Z",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """If text is exactly a markdown code-fence wrap, return the inner
    content. Otherwise return text unchanged.

    The match is whole-string (\\A ... \\Z). Any prose before or after
    the fence breaks the match and the original text is returned so the
    caller falls through to _rescue_json_object for anomalous
    contamination handling.
    """
    m = _FENCE_RE.match(text)
    if m is None:
        return text
    # Strip trailing whitespace inside the fence so the contract is "inner
    # content as clean JSON-as-string". The greedy DOTALL capture can include
    # a final newline when the model emits a blank line before the closing
    # fence (e.g. {"a":1}\n\n```); strip normalizes that out.
    return m.group(1).strip()


def _extract_final_assistant_text(events: list[dict]) -> str:
    """Concatenate all text blocks from the LAST assistant message that
    contains at least one text block. Returns empty string only if no
    assistant message in the stream has any text content (CCE-14).

    The orchestrator's downstream contract is that dispatch returns the
    canonical JSON dict; in stream-json mode the canonical JSON is the
    text content of the final assistant turn — possibly split across
    multiple text blocks if the model interleaved tool_use blocks.

    Hardened in CCE-14 against the forward-compat footgun where the
    LAST assistant turn is purely tool_use (no text). Prior implementation
    would return "" in that case even though earlier assistant turns
    contained the answer.
    """
    last_assistant_with_text: dict | None = None
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        content = ev.get("message", {}).get("content", [])
        has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
        if has_text:
            last_assistant_with_text = ev
    if last_assistant_with_text is None:
        return ""
    content = last_assistant_with_text.get("message", {}).get("content", [])
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _summarize_tool_use(events: list[dict]) -> dict:
    """Walk a stream-json event list and produce a tool-use summary.

    Two-pass algorithm:
      1. Collect `tool_result` outcomes keyed by `tool_use_id` from user events.
      2. Collect `tool_use` blocks from assistant events; join with outcomes
         from pass 1 so each call gets its `is_error` and `result_chars`.

    The `calls` list is capped at 50 to keep meta.json compact on chatty runs;
    `calls_truncated` flips True when the cap engages. Run-level fields
    (turns, stop_reason, duration_ms) come from the terminal `result` event.
    """
    errors_by_id: dict[str, bool] = {}
    result_chars_by_id: dict[str, int] = {}

    for ev in events:
        if ev.get("type") != "user":
            continue
        for block in ev.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tuid = block.get("tool_use_id", "")
            errors_by_id[tuid] = bool(block.get("is_error", False))
            content = block.get("content", "")
            if isinstance(content, list):
                content = "".join(
                    c.get("text", "") for c in content if isinstance(c, dict)
                )
            result_chars_by_id[tuid] = len(str(content))

    calls: list[dict] = []
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in ev.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tuid = block.get("id", "")
            input_preview = json.dumps(block.get("input", {}), default=str)[:200]
            calls.append(
                {
                    "name": block.get("name", ""),
                    "input_preview": input_preview,
                    "is_error": errors_by_id.get(tuid, False),
                    "result_chars": result_chars_by_id.get(tuid, 0),
                }
            )

    by_name: dict[str, int] = {}
    for c in calls:
        by_name[c["name"]] = by_name.get(c["name"], 0) + 1

    result_ev: dict = next((e for e in events if e.get("type") == "result"), {})

    return {
        "total_calls": len(calls),
        "by_name": by_name,
        "calls": calls[:50],
        "calls_truncated": len(calls) > 50,
        "turns": result_ev.get("num_turns"),
        "stop_reason": result_ev.get("stop_reason"),
        "duration_ms": result_ev.get("duration_ms"),
    }


# 45 min. Not a safe sizing, and the 60-min job limit it was once justified
# against is gone (both workflow files carry `timeout-minutes: 90` since
# CCE-140). See AUTHORING_TTL_SAFETY_SECONDS: at the default 900s merge poll this
# budget is squeezed flat by the App-token TTL, so a stock host gets no authoring
# overrun and is bounded by this number alone.
DEFAULT_TIME_BUDGET_SECONDS = 2700

DEFAULT_DEFERRAL_SKIP_THRESHOLD = 3

# CCE-152: how far past the soft budget the authoring loop may run in order to
# finish the PR it is in the middle of. 1.15 puts a 2100s host at ~2415s, which
# still leaves room for the merge poll (`merge.checks_timeout_seconds`, 900s)
# inside the GitHub App installation token's TTL — the real ceiling on a run,
# well under the workflow's own `timeout-minutes`.
#
# The ratio alone is NOT that guarantee, and its earlier wording claimed it was:
# it holds for a 2100s host (2415 + 900 = 3315 < 3600) and fails outright for
# the 2700s default (3104 + 900 = 4004 > 3600; `int()` floors, and `2700 * 1.15`
# is 3104.9999999999995). `resolve_authoring_hard_cap` clamps the product against
# GITHUB_APP_TOKEN_TTL_SECONDS so the bound is computed rather than asserted —
# for the overrun. A host whose ceiling is already at or below its budget is not
# clamped at all; see `resolve_authoring_hard_cap` for what that leaves unbounded.
DEFAULT_AUTHORING_HARD_CAP_RATIO = 1.15

# CCE-152: the GitHub App installation token the nightly workflow mints mid-job
# lives one hour, and no `timeout-minutes` extends it — it, not the job timeout,
# is the binding ceiling on a run. This existed only as prose (this module's
# comments, `templates/workflow-run.yml`, the README) until the hard cap needed
# to compute against it.
GITHUB_APP_TOKEN_TTL_SECONDS = 3600

# CCE-152: seconds held back inside the TTL for the work that happens after the
# authoring loop's last dispatch returns and after the merge poll settles — the
# in-flight page batch draining, the site generators, `git push`, the PR
# create/append, and the notifier dispatch.
#
# Chosen deliberately, and it is a tail reserve rather than a safety factor,
# because the ceiling it trims is already binding on a default-budget host. It
# has more to cover than the name suggests: the cut test is evaluated at the TOP
# of each authoring iteration, BEFORE that iteration dispatches, so the last
# admitted batch runs entirely past `authoring_hard_deadline`. The reserve has to
# absorb a whole page-author dispatch on top of the site generators, the push and
# the PR create.
#
# The criterion is maximality under the one constraint that binds: 285 is the
# LARGEST value that still leaves a 2100s host its full 1.15 overrun, since
# 2100 * 1.15 = 2415 <= 3600 - 900 - S solves to S <= 285. Larger, and the two
# hosts in this repo's orbit lose overrun they demonstrably have room for.
# Smaller buys nothing — no host in this repo's orbit gets a larger cap out of
# it — while leaving the tail funded for less work than it actually does.
AUTHORING_TTL_SAFETY_SECONDS = 285

DEFAULT_MERGE_POLICY = "auto"
DEFAULT_CHECKS_GRACE_SECONDS = 120
DEFAULT_CHECKS_TIMEOUT_SECONDS = 900
_CHECKS_POLL_INTERVAL_SECONDS = 15.0

# CCE-140 test seam: the last run's `advance_cursor_backed` decision. run()
# stamps it on every pass so an integration test can assert the gate input
# without threading a return value through run()'s int contract. Never read
# by production code — _maybe_auto_merge takes the value as an argument.
_LAST_ADVANCE_CURSOR_BACKED = False


def resolve_merge_settings(config: dict) -> dict:
    """CCE-101: resolve the merge-gate settings with default-ON semantics.

    Absent `merge:` block, absent `policy`, or a malformed (non-dict)
    block all resolve to auto — existing hosts flip on at tag pickup
    with zero config edits. Setup writes an explicit value for new hosts.
    """
    cfg = config.get("merge")
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "policy": cfg.get("policy", DEFAULT_MERGE_POLICY),
        "checks_grace_seconds": cfg.get(
            "checks_grace_seconds", DEFAULT_CHECKS_GRACE_SECONDS
        ),
        "checks_timeout_seconds": cfg.get(
            "checks_timeout_seconds", DEFAULT_CHECKS_TIMEOUT_SECONDS
        ),
    }


def _run_cfg(config: dict) -> dict:
    """The `run:` block as a dict — `{}` when absent, null, or malformed.

    CCE-152: one accessor for all three `run.*` resolvers. `resolve_time_budget`
    used `config.get("run") or {}`, which raises AttributeError on
    `run: "nonsense"`, while its two siblings resolved the same malformed block
    to defaults. The schema (`run` is `type: object`) rejects such a block at
    `load_config_validated`, so no host reaches a resolver with one — this is the
    inner layer, and it exists because the resolvers are also called with RAW
    dicts by their unit tests, where the schema is not in the path at all.
    """
    run_cfg = config.get("run")
    return run_cfg if isinstance(run_cfg, dict) else {}


def resolve_time_budget(config: dict, cli_override: int | None) -> int:
    """Resolve the per-run soft time budget in seconds.

    Precedence: CLI override (incl. explicit 0 = unlimited) > config
    `run.time_budget_seconds` > DEFAULT_TIME_BUDGET_SECONDS. A value <= 0 means
    "no budget" (unlimited); the caller turns that into deadline=None.
    """
    if cli_override is not None:
        return cli_override
    run_cfg = _run_cfg(config)
    val = run_cfg.get("time_budget_seconds")
    if val is None:
        return DEFAULT_TIME_BUDGET_SECONDS
    return int(val)


def resolve_deferral_threshold(config: dict) -> int:
    """Resolve `run.deferral_skip_threshold` (CCE-140).

    Absent `run:` block, a malformed (non-dict) block, or an absent key all
    resolve to DEFAULT_DEFERRAL_SKIP_THRESHOLD (3) — same default-ON posture
    as `resolve_merge_settings`, so an existing host gains the skip hatch with
    no config edit. A value <= 0 disables skipping.
    """
    run_cfg = _run_cfg(config)
    val = run_cfg.get("deferral_skip_threshold")
    if val is None:
        return DEFAULT_DEFERRAL_SKIP_THRESHOLD
    return int(val)


def resolve_authoring_hard_cap(
    config: dict, budget: int, *, out_reasons: list[str] | None = None
) -> int:
    """Resolve the ceiling (seconds) the authoring loop may never cross (CCE-152).

    The soft deadline is checked at PR-group boundaries so a run always finishes
    the oldest PR's pages and the cursor can advance. That deferral is unbounded
    on its own — one PR fanning out to twenty pages would hold the run open past
    the GitHub App installation token's TTL and fail it outright. This cap bounds
    the overrun: past it the loop cuts wherever it stands, which costs the advance
    but never costs the run.

    Precedence: `run.authoring_hard_cap_seconds` > budget *
    DEFAULT_AUTHORING_HARD_CAP_RATIO, then clamped down against the token TTL.

    **A cap at or below `budget` is rejected, not clamped up.** Equal is as bad as
    under: it collapses `authoring_hard_deadline` onto `deadline`, which makes
    the hard test equivalent to `now > deadline` and restores the arbitrary
    mid-group cut this ticket exists to remove. An operator who writes that has
    made a typo, and a silent `max(cap, budget)` would hide it behind exactly the
    starvation they were trying to configure away.

    **The TTL clamp is the structural half.** `budget * ratio` is a ratio, not a
    bound: at DEFAULT_TIME_BUDGET_SECONDS it yields 3104s (`int()` floors, and
    `2700 * 1.15` is 3104.9999999999995 in binary floating point — 3104 is what
    the digest prints), and 3104 plus the 900s merge poll is 4004s against a
    3600s token. Post-CCE-140 that poll runs on the common path (a cursor-backed
    run passes `merge_deadline=None`), so the overrun is reachable rather than
    theoretical. The ceiling is therefore
    computed: TTL - the merge poll this host will actually run - the tail
    reserve. The clamp applies to an explicit override too — the TTL is physics,
    and it does not care where the number came from.

    **When the ceiling lands at or below `budget`** the host's own budget plus
    its merge poll already fills the token, so there is no overrun left to grant.
    That is not a config error and must not abort: the budget itself may be
    perfectly serviceable, it just leaves no room on top. The cap is held at
    `budget` and the squeeze is appended to `out_reasons` for the caller to
    record. Behaviour degrades to pre-CCE-152 — cuts may again land mid-group and
    such a run earns no advance — which is never worse than before this ticket,
    and never silent.

    Note the asymmetry with the rejection above: both states are
    `hard_deadline == deadline`, and only one is refused. An operator override is
    a typo, correctable at the source. A TTL squeeze is arithmetic on a token
    nobody in this process controls, and refusing to run is strictly worse than
    running with the old cut behaviour.

    **The third state is a cap the clamp narrows** — legal (it is above the
    budget), not squeezed (the host keeps real overrun), but smaller than the
    number the cap resolved to. It is neither refused nor degraded, so it is
    reported: an `authoring_hard_cap_clamped` advisory naming the resolved cap,
    the ceiling, and the poll term that produced it. The number the operator
    reads back in the digest is then the one the run used, which is the whole
    reason the squeeze is loud too.

    The advisory fires on the ratio path too, not only on an explicit override,
    and says which one it is. There is no operator value to reconcile against on
    the ratio path, which is why it was silent originally — but the ceiling moves
    with `AUTHORING_TTL_SAFETY_SECONDS` and with this host's own merge poll, so a
    default that fit yesterday can be narrowed today with nothing said about it.
    An advisory line is a cheaper way to learn that than re-deriving the lattice.

    **The clamp bounds the overrun, not the budget, and only on these paths.**
    Neither the normal path nor the clamped path can return a cap that outlives
    the token. The squeeze path can: it returns `budget` with no ceiling applied,
    so a squeezed host is bounded by its own `run.time_budget_seconds` and
    nothing else, and `budget + poll` reaches the TTL exactly at the stock
    default and passes it as the budget grows. Bounding it here would mean
    truncating or refusing a run whose budget is otherwise serviceable, which
    design decision D2 forbids — degrade, never worse, never silent. The
    squeeze reason is the whole mitigation, and sizing is the operator's.
    """
    run_cfg = _run_cfg(config)
    val = run_cfg.get("authoring_hard_cap_seconds")
    if val is not None:
        cap = int(val)
        if cap <= budget:
            raise ConfigError(
                f"run.authoring_hard_cap_seconds ({cap}) must be greater than "
                f"the soft time budget ({budget}); a hard cap at or below the "
                f"budget makes the hard deadline the soft deadline, which cuts "
                f"page authoring mid-PR-group and blocks the baseline advance"
            )
    else:
        # `int()` floors, and `int(budget * 1.15) == budget` for every budget in
        # 1..6 — the computed path would land on exactly the collapsed state
        # (`cap == budget`) the explicit path above refuses. Only reachable from
        # small test fixtures, never from a real host, but the two paths must not
        # disagree about whether that state is legal. `budget <= 0` is the
        # unlimited host: no deadline, so no cap to raise off it.
        cap = int(budget * DEFAULT_AUTHORING_HARD_CAP_RATIO)
        if budget > 0:
            cap = max(cap, budget + 1)

    merge_settings = resolve_merge_settings(config)
    # Only an auto-merge host runs the checks poll; subtracting it from a
    # `policy: manual` host's ceiling would squeeze it for time it never spends.
    poll = (
        int(merge_settings["checks_timeout_seconds"])
        if merge_settings["policy"] == "auto"
        else 0
    )
    ceiling = GITHUB_APP_TOKEN_TTL_SECONDS - poll - AUTHORING_TTL_SAFETY_SECONDS
    if ceiling <= budget:
        if out_reasons is not None:
            out_reasons.append(
                f"authoring_hard_cap_squeezed: run.time_budget_seconds "
                f"({budget}s) plus the merge poll ({poll}s) plus the "
                f"{AUTHORING_TTL_SAFETY_SECONDS}s post-run tail already fills "
                f"the GitHub App token's {GITHUB_APP_TOKEN_TTL_SECONDS}s TTL, "
                f"so the authoring hard cap is held at the budget instead of "
                f"{cap}s. Page authoring can be cut mid-PR-group again and such "
                f"a run earns no baseline advance. Lower "
                f"run.time_budget_seconds or merge.checks_timeout_seconds."
            )
        return budget
    if cap > ceiling and out_reasons is not None:
        # The third state, and the only one that was silent. A squeeze is loud
        # and a rejection aborts; a cap narrowed by the TTL used to return a
        # number nobody wrote with nothing said about it, which reads as "my
        # config was ignored". Advisory rather than blocking: like the squeeze it
        # describes the host's configuration, not this run's work, and the run
        # itself is correctly bounded.
        #
        # Not gated on an explicit override. The gate was there because a ratio
        # default has no operator value to reconcile against, but the ceiling is
        # computed from AUTHORING_TTL_SAFETY_SECONDS and this host's own merge
        # poll — raising the reserve to 285 narrowed the ratio default harder for
        # every budget in 2101..2414 and took the overrun away silently. The
        # source clause is what keeps the message actionable in both cases: one
        # names a key to lower, the other a number nobody chose.
        _source = (
            "set in run.authoring_hard_cap_seconds"
            if val is not None
            else f"the {DEFAULT_AUTHORING_HARD_CAP_RATIO} default ratio applied "
            f"to run.time_budget_seconds {budget}s"
        )
        _remedy = (
            "Lower run.authoring_hard_cap_seconds to the value you will "
            "actually get, or lower merge.checks_timeout_seconds to earn more."
            if val is not None
            else "Lower merge.checks_timeout_seconds to earn more overrun, or "
            "set run.authoring_hard_cap_seconds explicitly to stop the "
            "difference moving under you."
        )
        out_reasons.append(
            f"authoring_hard_cap_clamped: the authoring hard cap resolves to "
            f"{cap}s ({_source}), which is above the {ceiling}s the App token's "
            f"{GITHUB_APP_TOKEN_TTL_SECONDS}s TTL leaves once the merge poll "
            f"({poll}s) and the {AUTHORING_TTL_SAFETY_SECONDS}s post-run tail "
            f"are held back, so the authoring hard cap is {ceiling}s for this "
            f"run. {_remedy}"
        )
    return min(cap, ceiling)


def _order_prs_oldest_first(
    prs: list[dict],
    *,
    last_sha: str,
    head_sha: str,
    repo_root: Path,
) -> list[dict]:
    """Return ``prs`` sorted oldest-merge-first by position in the window.

    CCE-109 correctness requirement: the admission gate truncates to a prefix,
    and the baseline advances to the last admitted PR. Processing oldest-first
    makes that prefix a contiguous oldest run, so advancing never skips an older
    PR. Order key = index of the PR's merge_sha in
    ``git rev-list --reverse`` over the window (oldest-first). An empty
    ``last_sha`` (first run) is NOT a passthrough: the window is the full
    history of ``head_sha``, so a truncated first run still gets a correct
    oldest-first prefix (otherwise the cursor could strand older PRs forever).
    PRs whose merge_sha is missing or out-of-window sort last (cannot anchor
    the cursor). Keys are 7-char prefixes — the same tolerance
    ``_clip_prs_to_window`` applies to the same data.

    Degrades gracefully: if git is unavailable/fails, returns ``prs``
    unchanged (mirrors ``_clip_prs_to_window``).
    """
    if not prs:
        return prs
    rev_range = f"{last_sha}..{head_sha}" if last_sha else head_sha
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", "--reverse", rev_range],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return prs
    if r.returncode != 0:
        return prs
    order = {
        sha.strip()[:7]: i for i, sha in enumerate(r.stdout.splitlines()) if sha.strip()
    }
    big = len(order) + 1

    def key(pr: dict) -> int:
        sha = (pr.get("merge_sha") or "").strip()
        return order.get(sha[:7], big)

    return sorted(prs, key=key)


def _last_processed_merge_sha(admitted_prs: list[dict]) -> str | None:
    """Return the merge_sha of the newest admitted PR that has one.

    ``admitted_prs`` is the oldest-first truncated prefix, so the newest admitted
    PR is the last element. Scan from the end for the first non-empty merge_sha.
    Returns None when no admitted PR carries a merge_sha (cannot anchor the
    cursor → caller must not advance).
    """
    for pr in reversed(admitted_prs):
        sha = (pr.get("merge_sha") or "").strip()
        if sha:
            return sha
    return None


def advance_cursor_list(
    admitted: list[dict],
    deferred_tail: list[dict],
    *,
    held_back: set,
) -> list[dict]:
    """Return the PR list whose newest merge_sha may anchor the advance.

    CCE-140. ``admitted`` is the oldest-first prefix this run processed;
    ``deferred_tail`` is the oldest-first remainder the admission gate never
    reached. Walk both in window order and stop at the first PR number in
    ``held_back``.

    The CCE-109 cursor is a PREFIX boundary: advancing the baseline to PR k's
    merge sha declares every PR at index <= k done. So the walk must stop at
    the OLDEST unfinished PR, never merely exclude it — advancing past it
    would strand it outside every future window, and nothing ever
    re-collects it.

    ``held_back`` carries PRs this run did not finish (admission-deferred or
    authoring-deferred) MINUS the ones forgiven by the CCE-140 deferral-skip
    hatch. Forgiveness is what lets the walk continue into ``deferred_tail``.

    With ``held_back`` empty and an empty tail this is the identity on
    ``admitted`` — the pre-CCE-140 behaviour.
    """
    out: list[dict] = []
    for pr in list(admitted) + list(deferred_tail):
        if pr.get("number") in held_back:
            break
        out.append(pr)
    return out


def deferral_key(repo: dict, pr_number) -> str:
    """`{owner}/{name}#{pr}` — one PR-identity shape across state.json.

    Same string the gap-detector builds for `pr_id`, and the same key shape
    `dismissed_gap_flags` uses, so an operator reading state.json sees one
    vocabulary.
    """
    return f"{repo['owner']}/{repo['name']}#{pr_number}"


def partition_deferrals(
    deferred: list[dict],
    *,
    counts: dict,
    repo: dict,
    threshold: int,
) -> tuple[list[dict], list[dict]]:
    """Split this run's deferred PRs into ``(skipped_now, still_deferred)``.

    CCE-140 / spec Decision 3: "Skip after 3 consecutive deferrals, record
    every skip durably, and enable notifications. A loud, recorded loss beats
    an indefinite silent stall."

    ``counts`` is the PRIOR consecutive-deferral map, so a PR whose stored
    count already equals ``threshold`` has been deferred on that many runs and
    this run is the (threshold+1)-th — the one that abandons it. ``threshold``
    <= 0 disables skipping entirely and every deferred PR stays deferred.

    Order-independent: the prefix-boundary invariant is enforced structurally
    by ``advance_cursor_list``, not here.
    """
    if threshold <= 0:
        return [], list(deferred)
    skipped: list[dict] = []
    still: list[dict] = []
    for pr in deferred:
        if int(counts.get(deferral_key(repo, pr.get("number")), 0)) >= threshold:
            skipped.append(pr)
        else:
            still.append(pr)
    return skipped, still


def next_deferral_counts(
    counts: dict,
    *,
    repo: dict,
    window_pr_numbers: set,
    still_deferred_numbers: set,
) -> dict:
    """Return the next persistent consecutive-deferral map (never mutates
    ``counts``).

    - in this window AND still deferred → count + 1
    - in this window and NOT still deferred → entry dropped. Covers both the
      processed case and the skipped case; "consecutive" means consecutive, so
      an intermittently-slow PR never accumulates toward a skip.
    - not in this window at all → carried forward unchanged. A window can
      shrink transiently when the source-collector degrades, and absence is
      not evidence a PR was processed. Growth is bounded because a PR leaves
      the window only once the baseline passes it, which requires it to be in
      the cursor prefix, which requires it not to be deferred.
    """
    out = dict(counts)
    for n in window_pr_numbers:
        k = deferral_key(repo, n)
        if n in still_deferred_numbers:
            out[k] = int(out.get(k, 0)) + 1
        else:
            out.pop(k, None)
    return out


# CCE-159: how long an unused summary-cache entry survives. A PR leaves the
# window for good once the baseline passes it, and its entry is dead weight
# after that. Eviction is by last-seen rather than by window membership on
# purpose: a window shrinks transiently when the source-collector degrades,
# and wiping the cache exactly when the pipeline is already struggling is the
# failure this retention exists to avoid.
PR_SUMMARY_RETENTION_DAYS = 30


def pr_summarizer_fingerprint() -> str:
    """Hash of the pr-summarizer agent definition (CCE-159).

    A cached summary is only valid for the instructions that produced it, so
    editing ``agents/pr-summarizer.md`` has to invalidate every entry. Hashing
    the file makes that automatic — there is no version constant anyone has to
    remember to bump, which is the failure mode a hand-maintained one has.

    An unreadable agent file returns ``""``, which matches no stored entry, so
    the cache fails closed to a full re-summarize rather than serving summaries
    it cannot prove are current.
    """
    try:
        return hashlib.sha256(
            (_AGENTS_DIR / "pr-summarizer.md").read_bytes()
        ).hexdigest()[:16]
    except OSError:
        return ""


def cached_pr_summary(
    cache: dict, pr: dict, *, repo: dict, fingerprint: str
) -> dict | None:
    """The stored summary for ``pr``, or None when it must be re-summarized.

    Three conditions, all of them necessary:

    - an entry exists under this PR's identity;
    - its ``merge_sha`` matches the PR's. A merged PR is immutable, which is
      what makes this cache exact rather than heuristic — a mismatch means the
      window is describing different content under the same number (rewritten
      history, a reopened-and-remerged PR) and the summary cannot be trusted;
    - its ``fingerprint`` matches the current agent definition.

    Returns the RAW agent output. The caller re-stamps ``pr_number`` from the
    PR itself, exactly as it does for a fresh dispatch, so a fixture-static
    echo in a stored summary cannot leak through.
    """
    if not fingerprint:
        return None
    entry = (cache or {}).get(deferral_key(repo, pr.get("number")))
    if not isinstance(entry, dict):
        return None
    if entry.get("fingerprint") != fingerprint:
        return None
    merge_sha = pr.get("merge_sha")
    if not merge_sha or entry.get("merge_sha") != merge_sha:
        return None
    summary = entry.get("summary")
    return summary if isinstance(summary, dict) else None


def next_pr_summaries(
    cache: dict,
    *,
    repo: dict,
    window_prs: list[dict],
    summary_by_number: dict,
    fingerprint: str,
    now: datetime,
    retention_days: int = PR_SUMMARY_RETENTION_DAYS,
) -> dict:
    """Return the next persistent summary cache (never mutates ``cache``).

    Lifecycle, mirroring ``next_deferral_counts``:

    - a PR this run holds a summary for → entry written, fingerprint and
      ``merge_sha`` stamped from this run;
    - a PR in this window with no usable summary → any existing entry is kept
      and its ``last_seen_at`` refreshed, so a PR that keeps being deferred
      never ages out while it is still being asked for;
    - everything else → carried forward until ``retention_days`` stale.

    A PR with no ``merge_sha`` is never stored. The sha is half the cache key's
    validity check, and an entry that cannot be invalidated is worse than no
    entry at all.
    """
    now_iso = now.isoformat()
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    out = {
        k: v
        for k, v in (cache or {}).items()
        if isinstance(v, dict) and str(v.get("last_seen_at") or "") >= cutoff
    }
    for pr in window_prs:
        number = pr.get("number")
        key = deferral_key(repo, number)
        summary = summary_by_number.get(number)
        merge_sha = pr.get("merge_sha")
        if isinstance(summary, dict) and merge_sha:
            out[key] = {
                "merge_sha": merge_sha,
                "fingerprint": fingerprint,
                "last_seen_at": now_iso,
                "summary": summary,
            }
        elif key in out:
            out[key] = {**out[key], "last_seen_at": now_iso}
    return out


def _git_is_ancestor(repo_root: Path, anc: str, desc: str) -> bool | None:
    """``git merge-base --is-ancestor`` as a tri-state: True/False, or None
    when the relation is unverifiable (bad object, no git, other git error).
    Output is captured (and discarded) so expected git fatals on the
    degraded path don't leak into the orchestrator's stderr.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", anc, desc],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


def _rev_parse_commit(repo_root: Path, sha: str) -> str | None:
    """Resolve ``sha`` (possibly abbreviated) to its full 40-hex commit id.

    CCE-109: the source-collector contract permits abbreviated merge_shas (its
    own example is 8-char), but the persisted baseline must be canonical —
    a stored prefix can turn ambiguous as the repo grows and never matches the
    CCE-43 guard's string comparison. None when unresolvable or git is
    unavailable.
    """
    try:
        r = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--verify",
                "--quiet",
                f"{sha}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def _sha_in_window(
    sha: str,
    *,
    last_sha: str,
    head_sha: str,
    repo_root: Path,
) -> tuple[bool, str]:
    """Return (ok, reason): ok only if ``sha`` is confirmed SAFE to advance
    the baseline to.

    CCE-109 spec Component 4 invariant guard. "Safe" means ``sha`` is an
    ancestor of ``head_sha`` (reachable from this run's HEAD) AND — when a
    baseline exists — a descendant of ``last_sha`` (strictly forward, so the
    cursor never regresses). An empty ``last_sha`` (first run) imposes no lower
    bound: any ancestor of HEAD is valid forward progress.

    On failure the reason names the cause so the partial reason distinguishes
    infra failure from data corruption: ``not_ancestor_of_head`` (garbage or
    foreign cursor), ``behind_baseline`` (would regress), or
    ``window_unverifiable`` (git missing/erroring — the uncomputable-window
    truncation path where ``_clip_prs_to_window`` and
    ``_order_prs_oldest_first`` both degrade to passthrough). The caller must
    not advance on any of them.
    """
    if not sha or not head_sha:
        return False, "window_unverifiable"
    anc = _git_is_ancestor(repo_root, sha, head_sha)
    if anc is None:
        return False, "window_unverifiable"
    if anc is False:
        return False, "not_ancestor_of_head"
    if not last_sha:
        return True, ""
    fwd = _git_is_ancestor(repo_root, last_sha, sha)
    if fwd is None:
        return False, "window_unverifiable"
    if fwd is False:
        return False, "behind_baseline"
    return True, ""


def _clip_prs_to_window(
    prs: list[dict],
    *,
    last_sha: str,
    head_sha: str,
    repo_root: Path,
    out_reasons: list[str] | None = None,
) -> list[dict]:
    """Drop PRs whose merge_sha is not in `git rev-list last_sha..head_sha`.

    CCE-19: source-collector's agent prompt doesn't reliably apply an upper
    bound on `gh pr list`, so in 3/5 baseline runs it returned PRs merged
    after head_sha. This helper is the orchestrator-side safety net.

    - Empty last_sha → first-run case; no lower bound exists, skip filtering.
    - PR without merge_sha → keep but record `merge_sha_missing` partial reason
      (older Mode-A fixtures predate the field).
    - PR with merge_sha not in the resolved SHA set → drop and record
      `out_of_window_dropped: PR #<n> sha=<short>` partial reason.

    Returns the filtered list; mutates `out_reasons` in place when supplied.
    """
    if not last_sha:
        return prs
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", f"{last_sha}..{head_sha}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        if out_reasons is not None:
            out_reasons.append("out_of_window_filter_skipped: git not available")
        return prs
    if r.returncode != 0:
        if out_reasons is not None:
            out_reasons.append(
                f"out_of_window_filter_skipped: git rev-list rc={r.returncode}"
            )
        return prs
    in_window = {sha.strip() for sha in (r.stdout or "").splitlines() if sha.strip()}
    in_window_short = {sha[:7] for sha in in_window}
    kept: list[dict] = []
    for pr in prs:
        sha = (pr.get("merge_sha") or "").strip()
        if not sha:
            if out_reasons is not None:
                out_reasons.append(f"merge_sha_missing: PR #{pr.get('number')}")
            kept.append(pr)
            continue
        if sha in in_window or sha[:7] in in_window_short:
            kept.append(pr)
            continue
        if out_reasons is not None:
            out_reasons.append(
                f"out_of_window_dropped: PR #{pr.get('number')} sha={sha[:8]}"
            )
    return kept


def dispatch_subagent(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    out_reasons: list[str] | None = None,
) -> dict | None:
    """Dispatch a subagent. Returns parsed JSON output, or None on failure.

    In dry-run mode, reads from `<dry_run_dir>/fake_<name_with_underscores>.json`
    instead of invoking Claude. Returns None if the fixture is missing.

    In production, the subprocess invocation:
    - wraps `inputs` in execution framing so Claude executes the agent's
      Job rather than analyzing the JSON as content (CCE-3 A)
    - sets `cwd` so the agent loads the target repo's CLAUDE.md and its
      git/gh state, not the plugin's (CCE-3 B)
    - passes `--plugin-dir` and `--allowedTools` so agents resolve and can
      run their declared tools non-interactively (CCE-3 C)

    When DOCS_AGENT_DEBUG_DIR is set (CCE-9 + CCE-12):
    - dispatch uses `--output-format stream-json --verbose` so we observe
      ground-truth tool-call sequence
    - raw NDJSON event stream is persisted to <agent>.stream.jsonl
    - extended <agent>.meta.json carries a tool_use summary block
    - the dict returned to callers is parsed from the FINAL assistant
      message's concatenated text content (caller contract preserved)

    Stream-json mode's per-run latency is dominated by the agent's
    tool-call decisions, NOT the NDJSON parse overhead (CCE-14). The
    CCE-12 baseline measured 3-6s for Category-A runs (zero tool calls)
    versus 74s for the Run-2 outlier that made 5 tool calls. This mode
    is appropriate for diagnostic measurement; for steady-state
    production, leave DOCS_AGENT_DEBUG_DIR unset so the simple --print
    path runs at full speed.

    Returns None if:
    - the `claude` binary is not installed (FileNotFoundError)
    - the subagent process exits with a non-zero return code
    - the subagent emits empty stdout (or in stream-json mode, no assistant text)
    - the subagent emits unparseable JSON
    """
    if dry_run_dir is not None:
        stem = f"fake_{name.replace('-', '_')}"
        # A `<stem>__pr<N>.json` fixture, when present, wins over the shared
        # one. Without it a dry run cannot model a window whose PRs produce
        # DIFFERENT doc targets: every PR reads the same file, so every page
        # batch contains every PR and the window can only land or fail as a
        # whole. The CCE-140 baseline rule — advance only to the last PR whose
        # pages all landed — says nothing under that constraint, which is why
        # its mixed case had no end-to-end coverage.
        pr = inputs.get("pr") if isinstance(inputs, dict) else None
        number = pr.get("number") if isinstance(pr, dict) else None
        if number is not None:
            per_pr = dry_run_dir / f"{stem}__pr{number}.json"
            if per_pr.exists():
                return load_json(per_pr)
        fixture = dry_run_dir / f"{stem}.json"
        if not fixture.exists():
            return None
        return load_json(fixture)

    prompt = _EXECUTION_FRAMING.format(payload=json.dumps(inputs))
    base_argv = [
        "claude",
        # CCE-15: --setting-sources project,local skips the user-level
        # settings.json where the explanatory-output-style plugin is
        # enabled (its SessionStart hook injects "★ Insight" prose into
        # subprocess context, which broke CCE-14 Run 4's output parsing).
        # Unlike --bare, this preserves OAuth/keychain authentication.
        # Project + local settings still load, but this repo has no
        # .claude/ dir so neither contributes plugin-enable state.
        "--setting-sources",
        "project,local",
        "-p",
        prompt,
        "--agent",
        name,
        "--plugin-dir",
        str(_PLUGIN_ROOT),
    ]
    agent_tools = _load_agent_allowed_tools(name)
    if agent_tools is not None:
        base_argv.extend(["--allowedTools", " ".join(agent_tools)])
    debug_dir = os.environ.get("DOCS_AGENT_DEBUG_DIR")
    argv = (
        base_argv + ["--output-format", "stream-json", "--verbose"]
        if debug_dir
        else base_argv
    )

    run_kwargs: dict = {"capture_output": True, "text": True, "check": False}
    if cwd is not None:
        run_kwargs["cwd"] = str(cwd)
    # CCE-10: pass CLAUDE_STOP_VERIFY=0 so the global stop-verify hook does
    # not contaminate subagent stdout with a "Verification statement:" prose
    # preamble that breaks json.loads(). See agents/source-collector.md and
    # ~/.claude/hooks/stop-verify.sh:22.
    run_kwargs["env"] = {**os.environ, "CLAUDE_STOP_VERIFY": "0"}
    try:
        r = subprocess.run(argv, **run_kwargs)
    except FileNotFoundError:
        return None

    # Parse subagent output. In stream-json mode the canonical JSON is the
    # final assistant message's text content; in simple-print mode it IS
    # the raw stdout.
    raw_stdout = r.stdout or ""
    tool_use_summary: dict | None = None
    if debug_dir:
        events: list[dict] = []
        for line in raw_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines; raw stream.jsonl preserves them for forensics.
                continue
        canonical_text = _extract_final_assistant_text(events)
        tool_use_summary = _summarize_tool_use(events)
    else:
        canonical_text = raw_stdout

    # CCE-9 + CCE-12: when DOCS_AGENT_DEBUG_DIR is set, write forensics
    # artifacts. The extra stream.jsonl is stream-json-only; the tool_use
    # block in meta.json is also stream-json-only.
    if debug_dir:
        debug_path = Path(debug_dir)
        debug_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        base = debug_path / f"{ts}-{name}"
        base.with_suffix(".prompt.txt").write_text(prompt)
        # stdout.txt holds the caller view (extracted canonical JSON), so
        # readers can diff against the simple-print mode's stdout.txt
        # without knowing which dispatch path produced it.
        base.with_suffix(".stdout.txt").write_text(canonical_text)
        base.with_suffix(".stderr.txt").write_text(r.stderr or "")
        base.with_suffix(".stream.jsonl").write_text(raw_stdout)
        meta_payload: dict = {"returncode": r.returncode, "argv": argv}
        if tool_use_summary is not None:
            meta_payload["tool_use"] = tool_use_summary
        base.with_suffix(".meta.json").write_text(json.dumps(meta_payload, indent=2))

    if r.returncode != 0:
        return None
    canonical_text = canonical_text.strip()
    if not canonical_text:
        return None
    # CCE-55: strip the markdown code-fence wrap if present. This is a
    # whole-string match — fence-only inputs strip to clean JSON and
    # parse without firing the rescue partial banner. Anything that
    # isn't a pure fence wrap passes through unchanged so the existing
    # _rescue_json_object path still handles anomalous contamination.
    parse_text = _strip_code_fence(canonical_text)
    try:
        return json.loads(parse_text)
    except json.JSONDecodeError:
        # CCE-15: strict parse failed. Try prose-tolerant rescue against
        # the ORIGINAL canonical_text (not the strip output) — if the
        # strip didn't change anything, both are identical; if it did,
        # we still want the rescue to see the full text in case the
        # contamination is more complex than a simple fence wrap.
        rescued = _rescue_json_object(canonical_text)
        if rescued is not None:
            if out_reasons is not None:
                out_reasons.append(f"prose_contamination_rescued: {name}")
            return rescued
        return None


def dispatch_validated(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    inject: dict | None = None,
) -> tuple[dict | None, list[str]]:
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid clean:           (raw_dict, [])
      Schema-valid + rescued (CCE-15):
                                    (raw_dict, ["prose_contamination_rescued: <name>"])
      Schema-invalid:               (None, [...reasons including any rescue tag])
      Dispatch-None:                (None, []) — caller adds its own generic reason
      Schema-missing:               (None, ["schema_missing: <name>"])

    ``inject`` (CCE-120): orchestrator-owned fields to stamp onto the raw
    agent output BEFORE validation. ``inject`` values override the agent's
    echo (``{**raw, **inject}``), so a field the orchestrator already owns
    (e.g. gap-detector's ``pr_id``) is authoritative and never depends on the
    LLM reproducing it. ``inject=None`` is a pure pass-through — the other
    call sites are unaffected. Only applied when ``raw`` is a dict; a non-dict
    agent response falls through to normal schema rejection unchanged.
    """
    # CCE-15: pass an out_reasons collector so dispatch_subagent can
    # surface prose-contamination rescue events; merge them into the
    # tuple returned to callers (orchestrator state accumulates them
    # into state['current_run']['partial_reasons']).
    dispatch_reasons: list[str] = []
    raw = dispatch_subagent(
        name, inputs, dry_run_dir=dry_run_dir, cwd=cwd, out_reasons=dispatch_reasons
    )
    if raw is None:
        return None, dispatch_reasons
    # CCE-120: stamp orchestrator-owned fields (e.g. pr_id) before validation
    # (see the docstring for the override/pass-through/non-dict contract).
    if inject and isinstance(raw, dict):
        raw = {**raw, **inject}
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, dispatch_reasons + reasons
    # Return raw (not the dataclass) so call sites can keep using dict.get() patterns.
    return raw, dispatch_reasons


def _record_dispatch_reasons(
    state: dict, reasons: list[str], *, ok: bool, degraded: bool = False
) -> None:
    """Record dispatch reasons, classified.

    When the dispatch SUCCEEDED (``ok=True``) its reasons are retry/warning
    noise: they are recorded ``info_only`` and must NOT flip ``partial``.
    When the dispatch failed (``ok=False``) the reasons explain dropped work
    and DO flip ``partial``.

    Advisory layers (fact-checker, deterministic generators) record
    ``info_only=True`` directly and do not route through this helper.

    CCE-144: a failed dispatch is BLIND by default — the agent never answered,
    so the pipeline was prevented from judging. Pass ``degraded=True`` at the
    two callsites whose failure holds work back rather than consuming it
    (page-author, whose unlanded batch keeps its PR out of the advance cursor;
    gap-detector, whose output is advisory and outside the merge gate).
    ``ok=True`` outranks ``degraded`` — an advisory reason is advisory.
    """
    for r in reasons:
        add_partial(state, r, info_only=ok, degraded=degraded)


def _exit_code(state: dict) -> int:
    """CCE-144: 1 when the run is blind, else 0.

    Exit 1 is not a new code — `run` already returns 1 when the docs PR could
    not be opened, which is the same class of signal ("this run failed, read
    the reasons"). Blind joins that class rather than competing with it, so an
    operator reading only the run status takes the same action for both.
    Exit 2 stays with the config-error paths.

    The exit code is the alarm channel because it is the only one requiring
    zero provisioning: GitHub's native failure email and a red run-history
    entry need no secret, no webhook, no config. It is also the only channel
    that survives total quota exhaustion, since nothing in this path invokes
    the Claude CLI — which is exactly the outage it must report.
    """
    return 1 if (state.get("current_run") or {}).get("blind") else 0


def _should_advance_watermark(state: dict) -> bool:
    """CCE-144: a blind run must not move `last_successful_run`.

    The cursor is consume-once — a window it skips is never re-read. On
    2026-08-12 a blind run advanced it past three feature PRs whose content
    was never authored, and that loss is permanent.

    Re-processing a window is cheap and idempotent. Skipping one is not, so
    the asymmetry decides: when in doubt, do not advance.

    Read at the moment of the advance. Two classes of blind reason are
    recorded downstream of that point, both deliberately: `notifier_invalid`,
    near the end of `run`, where it sets the exit code but cannot rewind a
    cursor that is already written — correctly, since a failed digest means
    the operator was not told while the authoring work itself completed and
    its watermark is honest; and every non-`info_only` failure raised inside
    `open_or_append_pr`, whose advance is honest for a different reason —
    per CCE-40 §7 row 3 it is ephemeral working-tree state, since a failed
    PR-open means nothing reaches `main` and the next nightly starts from a
    fresh checkout.
    """
    return not (state.get("current_run") or {}).get("blind")


def dispatch_verified(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    post_write_check: Callable[[Path, dict], tuple[bool, list[str]]] | None = None,
    target_path: Path | None = None,
    manifest_page: dict | None = None,
) -> tuple[dict | None, list[str]]:
    """Dispatch a subagent through ``dispatch_validated``, then run an optional
    post-write check against the artifact the agent produced.

    On check failure, ``target_path`` is unlinked so the next bootstrap run
    retries this page (the orchestrator's existing
    ``if target_path.exists(): skip`` idempotency is the retry mechanism). The
    augmented reason list is returned alongside ``out=None`` so the caller's
    ledger receives the rejection.

    ``post_write_check=None`` is a pure pass-through — callers that haven't
    opted in see no behavior change.
    """
    out, reasons = dispatch_validated(name, inputs, dry_run_dir=dry_run_dir, cwd=cwd)
    if out is None or post_write_check is None:
        return out, reasons
    if target_path is None:
        raise ValueError(
            "dispatch_verified: target_path is required when post_write_check is set"
        )
    ok, check_reasons = post_write_check(target_path, manifest_page or {})
    if ok:
        return out, reasons
    # Reject: delete the artifact and roll up the new reasons.
    try:
        target_path.unlink(missing_ok=True)
    except OSError as e:
        check_reasons.append(f"unlink_failed: {target_path}: {e}")
    return None, reasons + check_reasons


class _BootstrapProgress:
    """Best-effort per-page progress file for ``run_bootstrap_core``.

    Path: ``<repo_root>/.engineering-docs-agent/bootstrap.progress.json``.
    Write cadence: atomic (temp-file + ``os.replace``) on every transition.
    File is unlinked at end of run; an existing file is itself a signal that
    a run is in progress or crashed mid-flight.

    Assumes a single bootstrap writer per ``repo_root``. The fixed
    ``.tmp`` suffix means two concurrent processes would race on the same
    temp path; bootstrap is launched once per nightly run, so this is sound
    in production. Callers wiring this elsewhere should preserve that
    invariant.

    All write failures are logged to stderr; the bootstrap loop never aborts
    because of progress-file I/O errors.
    """

    def __init__(self, repo_root: Path, *, total: int) -> None:
        self._path = repo_root / ".engineering-docs-agent" / "bootstrap.progress.json"
        self._state: dict[str, Any] = {
            "phase": "bootstrap",
            "started_at": None,
            "total": total,
            "current_index": 0,
            "current_page": None,
            "current_page_started_at": None,
            "completed": [],
            "skipped_existing": [],
            "failed": [],
        }

    def _write(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._state, indent=2))
            os.replace(tmp, self._path)
        except OSError as e:
            emit_log(f"bootstrap.progress.json write failed: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def start(self) -> None:
        self._state["started_at"] = datetime.now(timezone.utc).isoformat()
        self._write()

    def begin_page(self, rel_posix: str) -> None:
        self._state["current_index"] += 1
        self._state["current_page"] = rel_posix
        self._state["current_page_started_at"] = datetime.now(timezone.utc).isoformat()
        self._write()

    def mark_completed(self, rel_posix: str) -> None:
        self._state["completed"].append(rel_posix)
        self._write()

    def mark_skipped(self, rel_posix: str) -> None:
        # Called after ``begin_page`` has already advanced ``current_index``
        # and set ``current_page``; the skip outcome is the only new state.
        self._state["skipped_existing"].append(rel_posix)
        self._write()

    def mark_failed(self, rel_posix: str, *, reason: str) -> None:
        self._state["failed"].append({"path": rel_posix, "reason": reason})
        self._write()

    def finish(self) -> None:
        """Unlink the progress file at end of run.

        If not called (e.g., the bootstrap process crashes mid-flight), the
        file remains on disk — that stale presence is the crash signal
        callers and humans use to detect an interrupted run.
        """
        try:
            self._path.unlink(missing_ok=True)
        except OSError as e:
            emit_log(f"bootstrap.progress.json cleanup failed: {e}")


def _page_target_is_editable(rel_posix: str, editable_globs: list[str]) -> bool:
    """True if a repo-relative page path may be authored: it matches at least
    one ``agent_editable_paths`` glob, or no globs are configured (permissive).
    Shared by the nightly authoring loop and ``run_bootstrap_core``.
    """
    return not editable_globs or any(
        fnmatch.fnmatch(rel_posix, g) for g in editable_globs
    )


def _core_page_skeleton(page: dict) -> str:
    """A deterministic, diagram-free Markdown body for a bootstrapped core page:
    a rationale stub the human must fill, a source-file inventory, and a
    gotchas/layering stub. No mermaid (waits on C3); no fabricated C1 pins
    (the production page-author emits verified pins).
    """
    title = page.get("title") or page.get("key") or "Component"
    src = page.get("source_files") or []
    lines = [
        f"# {title}",
        "",
        "TODO(human): rationale — why this component exists and its role in the system.",
        "",
        "## Source files",
        "",
    ]
    if src:
        lines.extend(f"- `{p}`" for p in src)
    else:
        lines.append("_No source files mapped._")
    lines += [
        "",
        "## Gotchas & layering rules",
        "",
        "TODO(human): rationale — accreted rules and constraints not derivable "
        "from current source.",
        "",
    ]
    return "\n".join(lines)


def _synthesize_core_page(target_path: Path, page: dict, today: str) -> None:
    """Dry-run stand-in for the production page-author: write a C2 core page
    (agent-authored frontmatter built from the manifest entry + injected
    ``today``, then the diagram-free skeleton). Mirrors the nightly dry-run
    synth but is manifest-aware.
    """
    import frontmatter_contract as fmc

    fm = fmc.agent_authored_frontmatter_text(
        description=page.get("title") or page.get("key") or "",
        source_files=page.get("source_files") or [],
        last_reviewed=today,
        status="draft",
    )
    target_path.write_text(fm + _core_page_skeleton(page))


def _synthesize_agent_description(
    summaries: list[dict], *, hint: str, min_words: int
) -> str:
    """Deterministic one-line description for a freshly-created agent-authored
    page (CCE-117). Guarantees the description_quality invariants — >= ``min_words``
    words, not equal to the slug-derived H1, no trailing colon — by construction.
    ``min_words`` is the host's resolved floor (CCE-119 Item B); pass
    ``description_quality.resolve_min_words(config)``. Pure; never raises on
    malformed input.
    """
    change = ""
    for s in summaries or []:
        if isinstance(s, dict):
            wc = s.get("what_changed") or s.get("why")
            if isinstance(wc, str) and wc.strip():
                change = wc.strip()
                break
    base = hint[:-3] if hint.endswith(".md") else hint
    topic = (
        " ".join(base.replace("/", " ").replace("-", " ").replace("_", " ").split())
        or "this page"
    )
    if change and len(change.split()) >= 3:
        desc = f"Documents {topic}: {change}"
    else:
        desc = f"Reference documentation for {topic} in this codebase"
    desc = desc.rstrip(":").strip()
    # CCE-119 Item B: pad deterministically to the resolved floor (was a
    # hardcoded 6). Neutral, repeatable filler drawn from the topic; each append
    # re-strips a trailing colon so the invariant holds wherever the floor lands.
    filler = f"agent-authored reference for {topic}".split()
    filler_index = 0
    while len(desc.split()) < min_words:
        desc = f"{desc} {filler[filler_index % len(filler)]}".rstrip(":").strip()
        filler_index += 1
    return desc


def _enforce_agent_frontmatter(path: Path, agent_fields: dict) -> None:
    """CCE-119 Item A: make the orchestrator's deterministic ``agent_fields`` the
    authoritative frontmatter of a freshly-created agent-authored page.

    The page-author (the real LLM on the production dispatch path) is handed
    these fields as a template but may reword or drop the lint-guarded ones; the
    orchestrator's values win — declare-then-discharge, never trust the
    subagent's own write. Strips whatever leading ``---`` block is on disk
    (mirroring the fence convention of ``archive_indexes.parse_frontmatter``:
    ``split("---", 2)``) and re-prepends
    ``agent_authored_frontmatter_text(**agent_fields)``, keeping the body.
    ``agent_fields`` carries only the four agent-authored keys (see Task 4's
    decoupling), so this never passes an unexpected kwarg. Idempotent; a file
    with no well-formed block keeps its whole text as the body.
    """
    import frontmatter_contract as fmc

    text = path.read_text()
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].lstrip("\n")
    path.write_text(fmc.agent_authored_frontmatter_text(**agent_fields) + body)


def _prior_page_text(repo_root: Path, path: Path) -> str | None:
    """The page as HEAD has it, or None for a new page / no commit."""
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        return None
    r = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{rel}"],
        capture_output=True,
    )
    if r.returncode != 0:
        return None
    # errors="replace", not text=True: git show's stdout is decoded with the
    # locale codec under text=True, so one non-UTF-8 byte in a committed page
    # raises out of subprocess.run itself — outside the caller's try — and
    # takes down the whole run. Under corroborated repair this is on the hot
    # path for every edit.
    return r.stdout.decode("utf-8", errors="replace")


def _diagnose_citation_paths(
    path: Path, repo_root: Path, config: dict, state: dict, source_paths: set[str]
) -> None:
    """CCE-141: report the tracked file a blocked citation was shortened from.

    DETECTION ONLY. This never rewrites the page — `citation_repair` has no
    `write_text` and this function must never grow one. Its module docstring
    records why the rewrite was deleted: four adversarial review rounds
    produced four Criticals, each the same class in a new disguise (a repair
    moving a citation into a region `citation_exists` does not verify, so a
    BLOCK became a silent PASS), against a measured production value of zero
    firings across the whole archived record.

    Called once per authored page AFTER the whole authoring loop and BEFORE
    the content-validator dispatch, so it reads the same finished tree
    `citation_exists` is about to read. The seam, and why it may not move
    below the lint-block revert, is documented at the call site in `run`.
    It reads, it reports, it returns.

    Classification: every line here is info_only=True. The decline line was
    degraded=True while a decline meant a page did not ship; THAT REASONING IS
    GONE. Nothing this function does affects whether the page ships. The page
    blocks because `citation_exists` blocks it, and that block is already
    reported and already classified (`lint_block`, degraded=True) — a second
    degraded reason would double-count one failure, and would cost the run
    auto-merge through CCE-140's `partial and not advance_cursor_backed` gate
    for a line that is pure advice. add_partial still records an info_only
    reason in `partial_reasons` and still emits it to stderr, so advisory is
    not silent.

    `source_paths` is the page's own batch grounding set and is REQUIRED. It is half of
    the corroborator ladder, which is what separates a confidently-labelled
    suggestion from a bare one; a default would let an un-threaded call site
    silently downgrade every finding to `uncorroborated`.

    The whole body is wrapped, and deliberately catches broadly. A diagnostic
    must never be fatal to an unattended nightly, and there is no top-level
    handler in `run()` or `main()` to fall back on: a `mkdocs.yml` whose top
    level is a YAML list or a bare scalar parses fine and then raises
    AttributeError on `.get` inside the linter helpers this reaches, which
    would take down the entire run for an advisory. The failure is itself
    reported as an advisory, for the same reason the findings are — it has no
    bearing on page correctness — but reported, because a diagnostic that
    silently stopped working is indistinguishable from one with nothing to say.
    """
    try:
        import citation_repair

        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            # citation_exists reports an unreadable/undecodable page itself; a
            # second, vaguer line from here would be noise.
            return
        files = citation_repair.tracked_files(repo_root)
        corroborators = citation_repair.build_corroborators(
            _prior_page_text(repo_root, path), source_paths, files
        )
        findings = citation_repair.diagnose(
            text, repo_root, config, files, corroborators
        )
        try:
            label = path.relative_to(repo_root).as_posix()
        except ValueError:
            label = path.name
        for cited, candidate, confidence in findings:
            add_partial(
                state,
                f"citation_shortening_suspected: {label}: '{cited}' -> "
                f"'{candidate}' ({confidence})",
                info_only=True,
            )
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never be fatal
        add_partial(
            state,
            f"citation_diagnosis_failed: {path.name}: {type(exc).__name__}: {exc}",
            info_only=True,
        )


def _resolve_docs_dir(config: dict) -> str | None:
    """The docs root for core pages: prefer ``site.docs_dir`` (what the manifest
    code and the source-map stage use), fall back to ``docs.source_dir`` for
    hosts that set no ``site:`` block. None when neither is a non-empty string.
    """
    site = config.get("site") if isinstance(config, dict) else None
    if isinstance(site, dict):
        d = site.get("docs_dir")
        if isinstance(d, str) and d.strip("/"):
            return d
    docs = config.get("docs") if isinstance(config, dict) else None
    if isinstance(docs, dict):
        d = docs.get("source_dir")
        if isinstance(d, str) and d.strip("/"):
            return d
    return None


def _load_core_manifest_pages(repo_root: Path, docs_dir: str) -> list[dict]:
    """The validated ``pages`` list from ``<docs_dir>/.doc-core-manifest.json``,
    or ``[]`` when the manifest is absent, unreadable, or carries no pages list.
    Never raises. Shared by ``run_bootstrap_core`` and ``compute_core_drift`` so
    both read the manifest through one contract.
    """
    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = load_json(manifest_path)
    except OSError:  # path is a dir, unreadable, etc. — degrade to no pages
        return []
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    return pages if isinstance(pages, list) else []


def _pr_changed_files(prs: list[dict]) -> set[str]:
    """File paths across PRs' files[] arrays (dict-with-path or plain string).
    Shared by source drift, citation drift, and page-author grounding."""
    out: set[str] = set()
    for pr in prs:
        for f in pr.get("files") or []:
            name = f.get("path") if isinstance(f, dict) else f
            if isinstance(name, str) and name:
                out.add(name)
    return out


def compute_source_drift(repo_root: Path, config: dict, prs: list[dict]) -> list[dict]:
    """Run the source-map generator and return drifted pages for this batch.
    Changed files = union of every PR's files[] (dict-with-path or plain string).
    Returns [] when no site/docs_dir is configured.
    """
    docs_dir = (config.get("site") or {}).get("docs_dir")
    if not docs_dir:
        return []
    # Deferred: both modules self-configure sys.path at load time.
    import source_map
    import source_drift

    source_map.generate_source_map(repo_root, docs_dir)
    changed = sorted(_pr_changed_files(prs))
    return source_drift.detect_drift(repo_root / docs_dir, changed)["drifted"]


def _drift_whats_new_lines(drifted_pages: list[dict]) -> list[str]:
    """What's-New block for drifted pages (empty list -> no block)."""
    if not drifted_pages:
        return []
    lines = ["### Pages to review (source drift)"]
    for d in drifted_pages:
        lines.append(f"- {d['page']} — changed: {', '.join(d['changed_sources'])}")
    return lines


def _changed_pages_from_map(
    repo_root: Path, docs_dir_rel: str, prs: list[dict]
) -> set[str] | None:
    """Pages (POSIX, relative to docs_dir) whose mapped source files changed in
    this batch, read from <docs_dir>/.doc-source-map.json. Returns None when the
    map is absent/unreadable (caller then verifies all pages).
    """
    map_path = repo_root / docs_dir_rel.rstrip("/") / ".doc-source-map.json"
    try:
        artifact = json.loads(map_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    source_to_pages = artifact.get("map")
    if not isinstance(source_to_pages, dict):
        return None
    changed = _pr_changed_files(prs)
    pages: set[str] = set()
    for src, page_list in source_to_pages.items():
        if src in changed and isinstance(page_list, list):
            pages.update(p for p in page_list if isinstance(p, str))
    return pages


def compute_citation_drift(repo_root: Path, config: dict, prs: list[dict]) -> dict:
    """Verify file:line citations for this batch and return the C1 ledger.
    Auto-fixes relocated citations in place (committed with the run's other doc
    edits). Scopes to pages whose mapped sources changed (via .doc-source-map.json),
    falling back to a full scan when no map exists. Empty ledger when no docs_dir.
    """
    import verify_citations as _vc

    docs_dir_rel = (config.get("site") or {}).get("docs_dir")
    if not docs_dir_rel:
        return _vc._empty_ledger()
    pages = _changed_pages_from_map(repo_root, docs_dir_rel, prs)
    return _vc.verify_citations(
        repo_root / docs_dir_rel, repo_root, fix=True, pages=pages
    )


def _citation_drift_whats_new_lines(ledger: dict) -> list[str]:
    """What's-New block for citation drift (empty list -> no block)."""
    pages = ledger.get("pages_review_needed") or []
    if not pages:
        return []
    lines = ["### Pages to review (citation drift)"]
    for g in ledger.get("gone", []):
        lines.append(f"- {g['page']} — citation gone: {g['path']} ({g['token']})")
    for a in ledger.get("ambiguous", []):
        lines.append(f"- {a['page']} — ambiguous: {a['path']} ({a['token']})")
    return lines


def compute_core_drift(
    repo_root: Path,
    config: dict,
    drifted_pages: list[dict],
    citation_ledger: dict,
) -> list[dict]:
    """Canonical-core pages (from ``.doc-core-manifest.json``) that M flagged as
    source-drifted or C1 flagged as citation ``gone``/``ambiguous``. Flag-only:
    reads the manifest and the already-computed M/C1 results, **writes nothing to
    any page and dispatches nothing**. Surfacing is independent of page status —
    a ``reviewed`` page that drifts is still surfaced so a human re-reviews.

    Returns a deterministically sorted list of ``{"page", "reasons"}`` where
    ``reasons`` is an ordered subset of ``["source", "citation"]``. Empty list
    when there is no docs_dir, no manifest, or no core page drifted.
    """
    # Non-empty output requires site.docs_dir: when a host has no site: block M
    # and C1 produce no drift, so the intersection is empty regardless of the
    # docs.source_dir fallback _resolve_docs_dir may return here.
    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        return []
    core_pages = {
        p["page"]
        for p in _load_core_manifest_pages(repo_root, docs_dir)
        if isinstance(p, dict) and isinstance(p.get("page"), str)
    }
    if not core_pages:
        return []
    source_drifted = {
        d["page"]
        for d in (drifted_pages or [])
        if isinstance(d, dict) and isinstance(d.get("page"), str)
    }
    citation_drifted = {
        e["page"]
        for key in ("gone", "ambiguous")
        for e in ((citation_ledger or {}).get(key) or [])
        if isinstance(e, dict) and isinstance(e.get("page"), str)
    }
    out: list[dict] = []
    for page in sorted(core_pages & (source_drifted | citation_drifted)):
        reasons = []
        if page in source_drifted:
            reasons.append("source")
        if page in citation_drifted:
            reasons.append("citation")
        out.append({"page": page, "reasons": reasons})
    return out


def _core_drift_whats_new_lines(core_drifted: list[dict]) -> list[str]:
    """What's-New block for drifted canonical-core pages (empty list -> no block)."""
    if not core_drifted:
        return []
    lines = ["### Core pages to review (drift)"]
    for d in core_drifted:
        lines.append(f"- {d['page']} ({', '.join(d['reasons'])})")
    return lines


def _compose_whats_new(existing: str, entry: str) -> str:
    """Insert `entry` as the newest dated section of a What's-New file.

    Preserves a leading YAML frontmatter block (``--- ... ---``) at line 1 and
    a following top-level ``# `` title heading, then inserts `entry` before the
    first ``## `` dated section so entries stay reverse-chronological. With no
    frontmatter/title the result reduces to the prior simple prepend
    (``entry + existing``); an empty file yields just `entry`.

    The frontmatter split mirrors ``archive_indexes.parse_frontmatter``
    (``text.split("---", 2)``), so the same delimiter assumptions apply.
    """
    if not existing.strip():
        return entry
    preamble = ""
    rest = existing
    if rest.startswith("---"):
        parts = rest.split("---", 2)
        if len(parts) == 3:
            preamble = "---" + parts[1] + "---"
            rest = parts[2]
    # Keep leading blanks + a single "# " title heading in the header region;
    # insert before the first "## " dated section (or at the end if none).
    lines = rest.splitlines(keepends=True)
    insert_at = next(
        (i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines)
    )
    header = "".join(lines[:insert_at])
    tail = "".join(lines[insert_at:])
    return preamble + header + entry + tail


def run_site_generators(repo_root: Path, config: dict, state: dict) -> dict:
    """Run the deterministic site generators when the host config has a `site:`
    block (CCE-104). These are the spec-correct CCE-23 generators — capability D
    (`archive_indexes.generate_archive`) and contracts (`contracts_doc.generate_contracts`,
    a no-op until a section declares the `json-schema` extractor, CCE-105).

    Best-effort like the source-map / citation stages: a generator that raises
    records an `info_only` partial and is swallowed, so an advisory generation
    failure never blocks the nightly PR. Generated pages land under the site's
    `docs_dir` and are committed by the run's existing `git add -A`.

    Returns ``{"archive": <ledger>|None, "contracts": <ledger>|None,
    "overviews": <ledger>|None}`` (None = not run / raised). Hosts with no
    `site:` block get all-None and fall through to the caller's legacy
    ``regenerate()`` path.
    """
    import archive_indexes
    import contracts_doc
    import section_overview

    result: dict = {"archive": None, "contracts": None, "overviews": None}
    site = config.get("site")
    if not site:
        return result
    try:
        result["archive"] = archive_indexes.generate_archive(repo_root, site)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        add_partial(state, f"archive_generate_failed: {exc}", info_only=True)
    try:
        result["contracts"] = contracts_doc.generate_contracts(repo_root, site)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        add_partial(state, f"contracts_generate_failed: {exc}", info_only=True)
    try:
        result["overviews"] = section_overview.generate_overviews(repo_root, site)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        add_partial(state, f"overview_generate_failed: {exc}", info_only=True)
    return result


def run(
    repo_root: Path,
    *,
    dry_run_dir: Path | None,
    no_pr: bool,
    time_budget_seconds: int | None = None,
    now_monotonic: Callable[[], float] | None = None,
) -> int:
    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    state_path = repo_root / ".engineering-docs-agent" / "state.json"
    if not cfg_path.exists():
        emit_log("no config")
        return 2

    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        emit_log(f"config invalid: {e}")
        return 2
    clock = now_monotonic or time.monotonic
    # CCE-152: `resolve_authoring_hard_cap` can reject the config (an
    # out-of-range hard cap), so it runs inside the same guard as the load above
    # and fails the run on the same terms as the two config rejections before it:
    # exit 2 with the reason on stderr. Outside the guard a ConfigError would
    # escape run() entirely — main() has no handler — and the operator would get
    # an unhandled traceback instead. Neither path notifies: the notifier
    # dispatch is at the very end of run(), far below this return, so a config
    # rejection here is silent to the digest either way.
    hard_cap_reasons: list[str] = []
    try:
        budget = resolve_time_budget(config, time_budget_seconds)
        authoring_hard_cap = resolve_authoring_hard_cap(
            config, budget, out_reasons=hard_cap_reasons
        )
    except ConfigError as e:
        emit_log(f"config invalid: {e}")
        return 2
    deadline = clock() + budget if budget > 0 else None
    # CCE-152: derived from `deadline` rather than a second clock() call. The
    # time-budget tests drive a fake clock through a counted value sequence, so
    # an extra call here would shift every gate after it.
    authoring_hard_deadline = (
        deadline + (authoring_hard_cap - budget) if deadline is not None else None
    )
    voice_samples = load_voice_samples(repo_root, config)
    try:
        state = load_state_validated(state_path)
    except StateError as e:
        emit_log(f"state invalid: {e}")
        return 2
    state.setdefault("version", "1")

    head_sha = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )

    repo = detect_repo(repo_root)

    # CCE-5: Always begin a new run with a fresh current_run. partial_reasons
    # from a prior run must not carry forward — persistent root causes will
    # re-accumulate naturally on this run's own dispatches; transient reasons
    # belong to the run that produced them.
    prior_run = state.pop("current_run", None)
    now = datetime.now(timezone.utc).isoformat()
    state["current_run"] = {
        "started_at": now,
        "head_sha": head_sha,
        "partial": False,
        "partial_reasons": [],
    }

    if prior_run is not None:
        prior_started = prior_run.get("started_at")
        if prior_started:
            try:
                prior_dt = datetime.fromisoformat(prior_started.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - prior_dt) > timedelta(hours=24):
                    add_partial(state, "stale_current_run_cleared", info_only=True)
            except ValueError:
                pass

    # CCE-152: the hard cap resolved above may have been squeezed flat, or
    # narrowed, against the App token's TTL — this list drains both
    # `authoring_hard_cap_squeezed` and `authoring_hard_cap_clamped`. Recorded
    # here, not at the resolve call, for the same reason the CCE-127 block below
    # sits here: `current_run` did not exist yet at the resolve, and the dict
    # literal above would have overwritten any stub add_partial created.
    # `info_only` because both describe the host's configuration, not this run's
    # work — they cost a run overrun, so they must reach the digest, but flipping
    # `partial` on a default-budget host every night would cost it auto-merge
    # (CCE-140 gates on `partial and not advance_cursor_backed`) for a condition
    # that predates this ticket.
    for _r in hard_cap_reasons:
        add_partial(state, _r, info_only=True)

    # CCE-127: the workflow's App-token step runs under continue-on-error, so a
    # failure to mint the installation token no longer kills the job — the run
    # degrades to secrets.GITHUB_TOKEN. Record that as a BLOCKING reason so
    # _maybe_auto_merge skips with "partial_run": a PR built on GITHUB_TOKEN
    # never fires host CI, and zero registered checks would otherwise read as
    # "nothing failed" and auto-merge unvalidated docs.
    #
    # Only the literal "failure" degrades the run. "skipped" is the documented
    # bare-host path (no DOCS_AGENT_APP_CLIENT_ID configured) and must stay
    # silent, as must "success" and unset. Placement is deliberate: after
    # current_run exists (add_partial would otherwise create a stub that the
    # dict literal above overwrites) and before the auto-merge decision.
    if os.environ.get("DOCS_AGENT_APP_TOKEN_STATUS", "") == "failure":
        _record_dispatch_reasons(
            state,
            [
                "app_token_unavailable: GitHub App installation token could not "
                "be minted; run degraded to GITHUB_TOKEN, so host CI will not "
                "fire on this PR. Verify the App is installed on this repo."
            ],
            ok=False,
        )

    try:
        # CCE-43: same-hour rerun guard. If origin/<docs-agent-branch>'s
        # committed state.json already advanced last_successful_run.head_sha
        # to our HEAD, the same window has already been processed. Proceeding
        # would mutate whats-new.md and state.json in the working tree with
        # content that differs from origin/<branch>, and the subsequent
        # checkout in open_or_append_pr would refuse (CCE-42 layer 3).
        skip_branch = branch_name(now)
        if _remote_already_processed_window(repo_root, skip_branch, head_sha):
            print(
                f"Skipped: origin/{skip_branch} already advanced "
                f"state.head_sha to {head_sha[:8]}; this window already "
                f"processed in this hour.",
                file=sys.stdout,
            )
            return _exit_code(state)

        jira_payload = config.get("sources", {}).get("jira")
        sc_inputs = {
            "last_sha": state.get("last_successful_run", {}).get("head_sha", ""),
            "head_sha": head_sha,
            "repo": repo,
            "pr_branch_filter": ["docs-agent/*"],
        }
        if jira_payload:
            sc_inputs["jira"] = jira_payload
        sources, reasons = dispatch_validated(
            "source-collector", sc_inputs, dry_run_dir=dry_run_dir, cwd=repo_root
        )
        _record_dispatch_reasons(state, reasons, ok=sources is not None)
        if sources is None:
            if not reasons:
                add_partial(
                    state, "source_collector_invalid: returned None", degraded=False
                )
            sources = {"prs": [], "jira_issues": []}
        else:
            if sources.get("error"):
                add_partial(
                    state, f"source_collector_error: {sources['error']}", degraded=False
                )
            if sources.get("partial"):
                add_partial(state, "source_collector_partial: true", degraded=False)

        # CCE-19: orchestrator-side safety net. The source-collector agent's
        # prompt was observed in 3/5 CCE-16 baseline runs to return PRs whose
        # merge_sha is outside last_sha..head_sha (agent applies merged_at
        # lower bound but ignores head_sha as an upper bound). Clip here so
        # downstream stages never see out-of-window PRs even if the agent
        # misses Step 1.5's SHA-range filter.
        clip_reasons: list[str] = []
        if isinstance(sources.get("prs"), list):
            sources["prs"] = _clip_prs_to_window(
                sources["prs"],
                last_sha=sc_inputs["last_sha"],
                head_sha=head_sha,
                repo_root=repo_root,
                out_reasons=clip_reasons,
            )
        for r in clip_reasons:
            add_partial(state, r, degraded=True)

        prs = sources.get("prs", [])
        prs = _order_prs_oldest_first(
            prs,
            last_sha=sc_inputs["last_sha"],
            head_sha=head_sha,
            repo_root=repo_root,
        )
        jira_issues = sources.get("jira_issues", []) or []
        jira_lookup = {issue["key"]: issue for issue in jira_issues}

        summaries = []
        lens_paths = config.get("docs", {}).get("lens_paths", {}) or {}
        available_sections_by_lens: dict[str, list[str]] = {}
        for _ln in lens_paths:
            try:
                _lp, _ = resolve_lens(config, _ln)
                _root = repo_root / _lp
                available_sections_by_lens[_ln] = (
                    sorted(
                        p.name
                        for p in _root.iterdir()
                        if p.is_dir() and not p.name.startswith(".")
                    )
                    if _root.is_dir()
                    else []
                )
            except (KeyError, OSError):
                available_sections_by_lens[_ln] = []
        time_truncated = False
        # CCE-140: the full window, oldest-first, before admission truncation.
        # Deferral counting is keyed to the window a run actually saw.
        window_prs = list(prs)
        # PRs the admission gate never reached (oldest-first), and the pages
        # an admitted PR still owes because the authoring loop was cut.
        admission_deferred: list[dict] = []
        deferred_pages_by_pr: dict[int, list[str]] = {}
        # CCE-140: bound on every path. A run that never truncates defers
        # nothing, and the deferral-count prune below runs on EVERY run — a
        # clean run is precisely what resets a PR's "consecutive" history.
        still_deferred: list[dict] = []
        # CCE-159: a merged PR's summary is a pure function of content that can
        # no longer change, so re-dispatching for it every night is pure waste.
        # Measured on the ADIS host: 52 of 58 PRs summarized on 2026-08-17 had
        # been summarized the night before — 90% repeat work, including every
        # PR that run went on to discard.
        _summary_cache = state.get("pr_summaries", {}) or {}
        _reuse_summaries = bool(
            (config.get("run") or {}).get("reuse_pr_summaries", True)
        )
        _summary_fingerprint = pr_summarizer_fingerprint()
        _summary_by_number: dict = {}
        _summaries_reused = 0
        for i, pr in enumerate(prs):
            if deadline is not None and i > 0 and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: admitted {i}/{len(prs)} PRs "
                    f"(budget {budget}s); deferring PR #{pr.get('number')} "
                    f"to next run",
                    degraded=True,
                )
                # A deferred PR without a merge_sha can't be re-anchored by the
                # next window — advancing past it would lose it forever, so the
                # advance block below must refuse when any exist. CCE-140 moves
                # that test into the advance block so it can be evaluated over
                # the STILL-deferred set (a PR forgiven by the deferral-skip
                # hatch is deliberately being lost and must not block).
                admission_deferred = prs[i:]
                prs = prs[:i]
                time_truncated = True
                break
            _cached = (
                cached_pr_summary(
                    _summary_cache, pr, repo=repo, fingerprint=_summary_fingerprint
                )
                if _reuse_summaries
                else None
            )
            if _cached is not None:
                _summaries_reused += 1
                _summary_by_number[pr["number"]] = _cached
                # Re-stamped from the PR, same as the fresh path below: a
                # stored summary's own pr_number echo is not authoritative.
                summaries.append({**_cached, "pr_number": pr["number"]})
                continue
            jira_context = [
                jira_lookup[k] for k in pr.get("jira_keys", []) if k in jira_lookup
            ]
            summary, reasons = dispatch_validated(
                "pr-summarizer",
                {
                    "pr": pr,
                    "jira_context": jira_context,
                    "lens_names": list(lens_paths.keys()),
                    "available_sections": available_sections_by_lens,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            _record_dispatch_reasons(state, reasons, ok=summary is not None)
            if summary is None:
                if not reasons:
                    add_partial(
                        state,
                        f"pr_summarizer_invalid: pr={pr['number']}",
                        degraded=False,
                    )
                continue
            if summary.get("error"):
                add_partial(
                    state,
                    f"pr_summarizer_error: pr={pr['number']}: {summary['error']}",
                    degraded=False,
                )
                continue
            # Use the PR's actual number, not summary's echo (which is fixture-static in tests).
            summary_with_pr = {**summary, "pr_number": pr["number"]}
            summaries.append(summary_with_pr)
            _summary_by_number[pr["number"]] = summary

        # Page authoring: batch doc_targets per (lens, page_hint).
        import frontmatter_contract as fmc
        import doc_routing

        archive_section = doc_routing.archive_section_leaf(config.get("site") or {})
        editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
        per_target: dict[tuple[str, str], list[dict]] = {}
        doc_kind_by_target: dict[tuple[str, str], str] = {}
        for s in summaries:
            for t in s.get("doc_targets", []):
                hint = t["page_hint"]
                dk = t.get("doc_kind")
                if t.get("action") == "create":
                    hint = doc_routing.route_create_hint(
                        hint,
                        dk,
                        archive_section,
                        available_sections_by_lens.get(t["lens"], []),
                    )
                key = (t["lens"], hint)
                per_target.setdefault(key, []).append(s)
                if dk and key not in doc_kind_by_target:
                    doc_kind_by_target[key] = dk

        authored: list[str] = []
        authored_lens: dict[str, str] = {}
        # CCE-141: the batch grounding each authored page was written against,
        # carried out of the loop. The diagnosis runs AFTER the loop (see the
        # seam comment below) and rung 2 of its run-input ladder needs the
        # page's OWN batch sources, not whichever batch happened to be last.
        grounding_by_path: dict[str, set[str]] = {}
        # CCE-140: the batch keys whose page actually landed. Everything in
        # per_target that is NOT in here owes its PRs a page — whatever the
        # reason: a time cut, a failed page-author dispatch, an unknown lens,
        # an unsafe path, or a lint block that reverted the file. Computing
        # "owed" as the COMPLEMENT of "landed" is what keeps the advance
        # cursor honest about failure modes nobody enumerated; an earlier
        # revision recorded only the time-truncated tail, so a run whose
        # page-author failed on batch 2 and then truncated at batch 4 still
        # advanced its baseline past batch 2's PR, permanently.
        landed_batches: set = set()
        batch_key_by_path: dict[str, tuple] = {}
        pr_by_number = {pr.get("number"): pr for pr in prs}
        # CCE-119 Item B: resolve the description_quality min_words floor once
        # from config (single source of truth in the lint rule) so an
        # agent-authored create's synthesized description clears a host's
        # possibly-raised threshold, not a hardcoded 6.
        _lint_dir = str(_PLUGIN_ROOT / "scripts" / "lint")
        if _lint_dir not in sys.path:
            sys.path.append(_lint_dir)
        import description_quality as _description_quality

        _desc_min_words = _description_quality.resolve_min_words(config)
        # CCE-152: the oldest PR referencing the batch authored one step back.
        # `per_target` is built by walking `prs` oldest-first and `setdefault`
        # never re-positions an existing key, so a batch's FIRST summary is its
        # oldest PR and the batch list is already grouped by owner, oldest group
        # first. That makes a group boundary detectable with one comparison.
        _prev_owner = None
        for i, ((lens, hint), batch_summaries) in enumerate(per_target.items()):
            _owner = batch_summaries[0].get("pr_number") if batch_summaries else None
            # CCE-114: the authoring fan-out is the most expensive phase (one
            # dispatch per batch), so it must respect the CCE-109 deadline —
            # admission alone happens too early to bound the run (all PRs are
            # admitted minutes in; run 27263616736 then authored straight
            # through the deadline into the workflow's 60-min hard kill).
            # The at-least-one-progress guarantee is no longer PR admission's
            # per-item `i > 0`: `i > 0` is necessary but not sufficient here,
            # because the cut must also land on a PR boundary. What this loop
            # guarantees is at least one COMPLETE PR GROUP — the `i > 0` escape
            # only keeps the very first batch unconditional so a run that was
            # already past its deadline on arrival still writes something.
            #
            # CCE-152: WHERE it may cut is the fix. Cutting at an arbitrary
            # batch index leaves the PR whose group was split owing a page, so a
            # run whose OLDEST PR fans out to more pages than the budget can
            # author splits group(PR1) every time: no PR ever completes,
            # `advance_cursor_list` breaks at index 0, and the baseline can
            # never move. ADIS sat on one baseline for 20.6 days on exactly
            # that — PR #646 restructured CLAUDE.md into ~6 pages against a
            # 1-5 page-per-run budget, and four nightlies in a row re-authored
            # the same leading pages and reported `no_advance_no_cursor`.
            #
            # So the soft deadline may only cut at a PR boundary, which always
            # leaves a COMPLETE prefix of PRs behind it. `authoring_hard_cap`
            # bounds how far finishing the current group may push the run.
            if deadline is not None and i > 0:
                _now = clock()
                _past_hard = (
                    authoring_hard_deadline is not None
                    and _now > authoring_hard_deadline
                )
                _at_boundary = _owner != _prev_owner
                if _now > deadline and (_at_boundary or _past_hard):
                    # Two reasons, one emission. Both are operator- and
                    # digest-facing prose with no structural consumer — nothing
                    # parses the `time_budget_exceeded: ` prefix
                    # (`_MERGE_VETO_REASON_PREFIXES` keys on
                    # `app_token_unavailable` only) — so the shared prefix is
                    # kept stable for greppability across historical runs rather
                    # than for a parser. Only the parenthetical and the trailing
                    # clause distinguish a boundary deferral from a hard-cap cut.
                    # The hard-cap wording is bounded and honest about the cost —
                    # that run does not earn an advance, the same standstill as
                    # before CCE-152, never worse, and it keeps the run inside
                    # its token.
                    if _past_hard and not _at_boundary:
                        if authoring_hard_cap == budget:
                            # A TTL-squeezed host (the stock default is one):
                            # the cap was held AT the budget, so "hard cap 2700s
                            # over budget 2700s" would read as a contradiction
                            # and hide the reason the overrun is missing.
                            _cut_detail = (
                                f"(hard cap held at budget {budget}s by the "
                                f"App-token TTL); cut inside PR #{_owner}, "
                                f"whose pages are now incomplete, so the "
                                f"baseline cannot advance to it"
                            )
                        else:
                            _cut_detail = (
                                f"(hard cap {authoring_hard_cap}s over budget "
                                f"{budget}s); cut inside PR #{_owner}, whose "
                                f"pages are now incomplete, so the baseline "
                                f"cannot advance to it"
                            )
                    else:
                        _cut_detail = f"(budget {budget}s); deferring the rest"
                    add_partial(
                        state,
                        f"time_budget_exceeded: authored {i}/{len(per_target)} "
                        f"page batches " + _cut_detail,
                        degraded=True,
                    )
                    # Track A: an authoring truncation is a truncation. Without
                    # this the advance block below falls through to
                    # current_run.head_sha and the run persists a baseline
                    # covering PRs whose pages it never wrote.
                    #
                    # CCE-140: an admitted PR whose page batch was never written
                    # is NOT done. The deferred tail is not recorded here — the
                    # complement pass after the lint block covers it, along with
                    # every other way a batch can fail to land.
                    time_truncated = True
                    break
            # Advance the owner BEFORE the `continue` paths below (unknown_lens,
            # unsafe_page_path). Leaving it until the end of the body would let a
            # skipped batch strand `_prev_owner` on an older PR, inventing a
            # boundary that is not there — or hiding one that is.
            _prev_owner = _owner
            try:
                lens_path, _opts = resolve_lens(config, lens)
            except KeyError:
                add_partial(state, f"unknown_lens: {lens}", degraded=True)
                continue
            target_path = repo_root / lens_path / hint
            try:
                rel = target_path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                add_partial(state, f"unsafe_page_path: {hint}", degraded=True)
                continue
            if not _page_target_is_editable(str(rel), editable_globs):
                add_partial(state, f"unsafe_page_path: {rel}", degraded=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = "edit" if target_path.exists() else "create"
            # CCE-110 layer 1: ground the author in the code the PRs touched.
            # Computed before the template so an agent-authored create can cite
            # the same files in source_files (CCE-117).
            batch_prs = [
                pr_by_number[s.get("pr_number")]
                for s in batch_summaries
                if s.get("pr_number") in pr_by_number
            ]
            grounding = _pr_changed_files(batch_prs)
            # CCE-117: agent-authored sections require description/source_files/
            # last_reviewed; the default template omits them, so Tier-1 lint
            # would drop the new page. Create-only — edits keep the existing
            # page's curated frontmatter (spec degradation table: an edit skips
            # reconciliation, so accumulated source_files / a published status are
            # never clobbered). `action` is captured above BEFORE dispatch, when
            # the file does not yet exist, so a genuine production create — the
            # LLM writes the page during dispatch — is still covered: `create`
            # holds here and `target_path.exists()` is True at the reconciliation
            # guard below. agent_fields is reused by the dry-run synth.
            agent_fields = None
            if (
                action == "create"
                and fmc.section_generator_for(rel, config) == "agent-authored"
            ):
                agent_fields = fmc.agent_authored_frontmatter_dict(
                    description=_synthesize_agent_description(
                        batch_summaries, hint=hint, min_words=_desc_min_words
                    ),
                    source_files=sorted(grounding),
                    last_reviewed=now[:10],  # date portion (YYYY-MM-DD) of the run
                )
                # CCE-119 Item A: keep agent_fields the pure 4-field authoritative
                # set. doc_kind is attached to a COPY below (it is routing-only —
                # nothing reads it back from a page), so reconciliation's
                # agent_authored_frontmatter_text(**agent_fields) can't hit the
                # latent doc_kind TypeError.
                fm_template = dict(agent_fields)
            else:
                fm_template = fmc.default_frontmatter_dict(
                    [
                        pr.get("url")
                        for s in batch_summaries
                        for pr in prs
                        if pr.get("number") == s.get("pr_number")
                    ]
                )
            _dk = doc_kind_by_target.get((lens, hint))
            if _dk:
                fm_template["doc_kind"] = _dk
            out, reasons = dispatch_validated(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": action,
                    "lens": lens,
                    "summaries": batch_summaries,
                    "voice_samples": voice_samples,
                    "frontmatter_template": fm_template,
                    "source_paths": sorted(grounding),
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            # CCE-144: degraded, not blind. An unlanded batch is folded into
            # deferred_pages_by_pr by the complement writer below, holding its
            # PR out of the advance cursor — the page is re-authored next run.
            _record_dispatch_reasons(state, reasons, ok=out is not None, degraded=True)
            if out is None:
                if not reasons:
                    add_partial(state, f"page_author_invalid: {rel}", degraded=True)
                continue
            if out.get("ok"):
                authored.append(str(target_path))
                authored_lens[str(target_path)] = lens
                grounding_by_path[str(target_path)] = grounding
                # CCE-140: provisionally landed. A lint block below can still
                # revert this page, which discards the entry again.
                landed_batches.add((lens, hint))
                batch_key_by_path[str(target_path.resolve())] = (lens, hint)
                if dry_run_dir and not target_path.exists():
                    # CCE-117: mirror the template branch so the dry-run synth
                    # writes the same generator-aware frontmatter the real
                    # page-author would, keeping tests on the real lint path.
                    fm_text = (
                        fmc.agent_authored_frontmatter_text(**agent_fields)
                        if agent_fields is not None
                        else fmc.default_frontmatter_text()
                    )
                    target_path.write_text(
                        fm_text + f"# {hint}\n\nGenerated by docs-agent.\n"
                    )
                if agent_fields is not None and target_path.exists():
                    # CCE-119 Item A: enforce the deterministic frontmatter on the
                    # written page (production: the LLM wrote it; dry-run: the synth
                    # above wrote it). Runs on both paths; a no-op when the write
                    # already matches.
                    _enforce_agent_frontmatter(target_path, agent_fields)

        # CCE-141: DIAGNOSE shortened citations, over the FINISHED tree.
        #
        # This ran INSIDE the authoring loop until the seam was moved. There it
        # evaluated `_resolves` against a tree that was still being built, so a
        # page citing a sibling the SAME RUN authors later — the ordinary shape
        # of a docs page — was diagnosed before that sibling existed and earned
        # a digest line for a citation `citation_exists` accepts on the finished
        # tree. A digest that flags citations the linter accepts is not a
        # census; it is noise that trains an operator to ignore it.
        #
        # Placed AFTER the whole authoring loop and BEFORE the content-validator
        # dispatch. That is the seam where the two views agree:
        #   * every page this run authored is on disk, so `_resolves` sees the
        #     same tree `citation_exists` is about to see inside
        #     content-validator;
        #   * `grounding_by_path` carries rung 2's batch sources out of the
        #     loop, per page, so the label still rests on the page's own batch;
        #   * nothing has been reverted yet. It must NOT move BELOW the
        #     lint-block revert: a reverted EDIT is restored from HEAD and still
        #     exists, so diagnosing it down there would report the PREVIOUS
        #     COMMIT's citations as if this run had written them — and a
        #     lint-blocked page is precisely the population this diagnostic
        #     exists to explain, so skipping those pages would leave it with
        #     nothing to say.
        # Deliberately NOT nested under any agent_fields guard: a shortened
        # citation blocks any page, not only the agent-authored ones.
        for _authored_page in authored:
            _authored_path = Path(_authored_page)
            if not _authored_path.exists():
                continue
            _diagnose_citation_paths(
                _authored_path,
                repo_root,
                config,
                state,
                source_paths=grounding_by_path.get(_authored_page, set()),
            )

        # Content validation
        if authored:
            validation, reasons = dispatch_validated(
                "content-validator",
                {
                    "paths": authored,
                    "config_path": str(cfg_path),
                    "voice_samples": voice_samples,
                    "plugin_root": str(_PLUGIN_ROOT),
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            _record_dispatch_reasons(state, reasons, ok=validation is not None)
            if validation is None:
                if not reasons:
                    add_partial(
                        state,
                        "content_validator_invalid: returned None",
                        degraded=False,
                    )
                validation = {"failed": []}
            for fail in validation.get("failed", []):
                if fail.get("severity") == "block":
                    fail_path = Path(fail["path"])
                    # Interpret relative paths as repo-relative (some subagent
                    # implementations may strip the repo prefix from echoed paths).
                    if not fail_path.is_absolute():
                        fail_path = repo_root / fail_path
                    # Verify path is inside repo_root before any destructive op.
                    try:
                        rel = fail_path.resolve().relative_to(repo_root.resolve())
                    except ValueError:
                        add_partial(
                            state,
                            f"lint_block_unsafe_path: {fail['path']} (outside repo)",
                            degraded=True,
                        )
                        continue
                    # Reject empty / "." paths that would cause git checkout HEAD -- .
                    # to restore the entire working tree.
                    if str(rel) in (".", ""):
                        add_partial(
                            state, "lint_block_unsafe_path: empty path", degraded=True
                        )
                        continue
                    # If the file exists in HEAD, restore it (edit case).
                    # If not (create case), remove it.
                    in_head = (
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(repo_root),
                                "cat-file",
                                "-e",
                                f"HEAD:{fail_path.relative_to(repo_root)}",
                            ],
                            capture_output=True,
                        ).returncode
                        == 0
                    )
                    if in_head:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(repo_root),
                                "checkout",
                                "HEAD",
                                "--",
                                str(fail_path.relative_to(repo_root)),
                            ],
                            check=False,
                        )
                    else:
                        fail_path.unlink(missing_ok=True)
                        cleanup_empty_parents(fail_path, until=repo_root)
                    add_partial(
                        state,
                        f"lint_block: {fail['path']} {fail['rule']}: {fail['message']}",
                        degraded=True,
                    )
                    # CCE-140: the page was just reverted or deleted, so its
                    # batch did NOT land and its PRs are still owed a page.
                    # Without this the cursor treats a lint-blocked PR as done
                    # and the baseline advances past content that was undone
                    # moments earlier.
                    landed_batches.discard(
                        batch_key_by_path.get(str(fail_path.resolve()))
                    )

        # CCE-140: fold every batch that did not land into the owed map, so
        # the advance cursor holds those PRs out of its prefix (spec Decision
        # 2: "the baseline advances only to the last PR whose pages all
        # landed"). This is the ONLY writer of deferred_pages_by_pr, and it is
        # a complement rather than a sum of failure sites on purpose: a new
        # `continue` added to the authoring loop later is covered for free,
        # whereas an enumeration would silently stop being exhaustive.
        for (_lens, _hint), _batch in per_target.items():
            if (_lens, _hint) in landed_batches:
                continue
            _label = f"{_lens}/{_hint}"
            for _s in _batch:
                _n = _s.get("pr_number")
                if _n is None:
                    continue
                _owed = deferred_pages_by_pr.setdefault(_n, [])
                if _label not in _owed:
                    _owed.append(_label)

        # CCE-110 layer 3: factual-accuracy fact-checker (warn layer). One
        # dispatch per surviving authored page that cites >=1 resolvable repo
        # source. Findings are operator-facing warnings only: info_only
        # reasons, a PR-body section, and the run record — never a partial
        # flag, never a dropped page. (Sole exception: a CCE-114 time-budget
        # cut of this loop DOES flip partial — see the guard inside.)
        fact_warnings: list[str] = []
        fact_pages = [p for p in authored if Path(p).exists()]
        if fact_pages:
            # Append (not insert(0)) so scripts/lint modules can never shadow
            # stdlib or scripts/ modules already importable by this process.
            lint_dir = str(_PLUGIN_ROOT / "scripts" / "lint")
            if lint_dir not in sys.path:
                sys.path.append(lint_dir)
            import citation_exists as _citation_exists

            for i, page in enumerate(fact_pages):
                # CCE-114: advisory layer — skip the remaining pages outright
                # once the deadline passes (no at-least-one guarantee; every
                # post-deadline second risks the hard kill). The reason stays
                # NOT info-only, but CCE-140 changed what that buys: it no
                # longer implies "must not auto-merge". `partial` alone stops
                # blocking the merge, and CCE-140 Decision 4 makes the
                # fact-checker non-gating in both directions — its warnings
                # do not block a merge, so its ABSENCE cannot either. What
                # the non-info flag still does is mark the run degraded for
                # the digest and the PR body. A veto here would re-stall the
                # pipeline on the most common truncation there is, which is
                # the failure this epic exists to end; the safety the merge
                # actually rests on is the cursor, which advances only past
                # PRs whose pages landed.
                if deadline is not None and clock() > deadline:
                    add_partial(
                        state,
                        f"time_budget_exceeded: fact-checked {i}/"
                        f"{len(fact_pages)} pages (budget {budget}s); "
                        f"skipping the rest",
                        degraded=True,
                    )
                    break
                page_path = Path(page)
                try:
                    page_text = page_path.read_text()
                except (OSError, UnicodeDecodeError):
                    # Unreadable or non-UTF-8 page: warn layer skips, never
                    # crashes the run (UnicodeDecodeError is a ValueError,
                    # not an OSError).
                    continue
                cited_sources = _citation_exists.resolve_cited_sources(
                    page_text, repo_root, _citation_exists.source_roots(config)
                )
                if not cited_sources:
                    continue
                try:
                    page_rel = str(page_path.resolve().relative_to(repo_root.resolve()))
                except ValueError:
                    page_rel = page
                fc_out, fc_reasons = dispatch_validated(
                    "fact-checker",
                    {
                        "page_path": page_rel,
                        "cited_sources": cited_sources,
                        "lens": authored_lens.get(page, ""),
                        "plugin_root": str(_PLUGIN_ROOT),
                    },
                    dry_run_dir=dry_run_dir,
                    cwd=repo_root,
                )
                for r in fc_reasons:
                    add_partial(state, r, info_only=True)
                if fc_out is None:
                    add_partial(
                        state,
                        f"fact_checker_unavailable: {page_rel}",
                        info_only=True,
                    )
                    continue
                if fc_out.get("verdict") == "contradiction":
                    for finding in fc_out.get("findings", []):
                        claim = (finding.get("claim") or "").strip()
                        src = (finding.get("source_path") or "").strip()
                        suffix = f" (vs `{src}`)" if src else ""
                        fact_warnings.append(f"`{page_rel}`: {claim}{suffix}")
        state["current_run"]["fact_check_warnings"] = fact_warnings

        # Deterministic site generators (CCE-104). When the host config carries a
        # site: block, run the spec-correct CCE-23 generators (archive capability
        # D + contracts); otherwise fall back to the legacy pre-S lens path so
        # hosts that set `archive_index: true` keep working (graceful degradation).
        if config.get("site"):
            state["current_run"]["site_generators"] = run_site_generators(
                repo_root, config, state
            )
        else:
            import archive_indexes

            for lens in lens_paths:
                try:
                    lens_path, opts = resolve_lens(config, lens)
                except KeyError:
                    continue
                if opts.get("archive_index"):
                    archive_indexes.regenerate(repo_root / lens_path)

        # Source map + drift (M) — best-effort, read-only
        try:
            drifted_pages = compute_source_drift(repo_root, config, prs)
        except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
            drifted_pages = []
            add_partial(state, f"source_map_failed: {exc}", info_only=True)
        state["current_run"]["source_drift"] = drifted_pages

        # Citation verification + drift (C1) — best-effort; auto-fixes relocated
        # citations in place (committed with the run's other doc edits).
        try:
            citation_ledger = compute_citation_drift(repo_root, config, prs)
        except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
            # Inline the empty ledger: if the failure was importing verify_citations
            # itself, re-importing here would re-raise and defeat the best-effort guard.
            citation_ledger = {
                "checked": 0,
                "ok": 0,
                "relocated": [],
                "ambiguous": [],
                "gone": [],
                "pages_review_needed": [],
            }
            add_partial(state, f"verify_citations_failed: {exc}", info_only=True)
        state["current_run"]["citation_drift"] = citation_ledger

        # Canonical-core drift (C2) — flag-only sibling after M/C1. Intersects the
        # core manifest with the M/C1 drift results; never edits a page or dispatches.
        try:
            core_drifted = compute_core_drift(
                repo_root, config, drifted_pages, citation_ledger
            )
        except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
            core_drifted = []
            add_partial(state, f"core_drift_failed: {exc}", info_only=True)
        state["current_run"]["core_drift"] = core_drifted

        # Gap detection
        dismissed = set(state.get("dismissed_gap_flags", {}).keys())
        gap_verdicts = []
        for i, pr in enumerate(prs):
            # CCE-114: advisory layer — skip entirely once the deadline
            # passes, same posture as the fact-checker loop above.
            if deadline is not None and clock() > deadline:
                add_partial(
                    state,
                    f"time_budget_exceeded: gap-checked {i}/{len(prs)} PRs "
                    f"(budget {budget}s); skipping the rest",
                    degraded=True,
                )
                break
            pr_id = f"{repo['owner']}/{repo['name']}#{pr['number']}"
            if pr_id in dismissed:
                continue
            verdict, reasons = dispatch_validated(
                "gap-detector",
                {
                    "pr_id": pr_id,
                    "pr": pr,
                    "config": {
                        "allowlist_paths": config.get("gap_detection", {}).get(
                            "allowlist_paths", []
                        ),
                        "size_filter": config.get("gap_detection", {}).get(
                            "size_filter", {}
                        ),
                    },
                    "dismissed_flags": list(dismissed),
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
                inject={"pr_id": pr_id},  # CCE-120: orchestrator-authoritative identity
            )
            # CCE-144: degraded, not blind. gap-detector output feeds only a
            # PR note and is excluded from the CCE-101 auto-merge gate, so a
            # failure here consumes no docs content.
            _record_dispatch_reasons(
                state, reasons, ok=verdict is not None, degraded=True
            )
            if verdict is None:
                if not reasons:
                    add_partial(
                        state, f"gap_detector_invalid: pr_id={pr_id}", degraded=True
                    )
                continue
            if verdict.get("needs_spec") is None:
                # CCE-125: a validated null needs_spec is the agent's "couldn't
                # judge" sentinel — advisory, not dropped work. Record it
                # info-only and skip it (never appended, so it stays out of
                # "Gaps flagged" and the digest); the run stays non-partial.
                add_partial(
                    state,
                    f"gap_detector_unjudged: pr_id={pr_id}",
                    info_only=True,
                )
                continue
            gap_verdicts.append(verdict)

        # Prepend What's New entry (only if we have PRs to report)
        if prs:
            whats_new = repo_root / config["docs"]["whats_new_file"]
            whats_new.parent.mkdir(parents=True, exist_ok=True)
            entry_lines = [f"## {now}"]
            for s in summaries:
                entry_lines.append(
                    f"- PR #{s.get('pr_number')}: {s.get('what_changed', '')}"
                )
            gaps_flagged = [v for v in gap_verdicts if v.get("needs_spec")]
            if gaps_flagged:
                entry_lines.append("### Gaps flagged")
                for g in gaps_flagged:
                    entry_lines.append(f"- {g['pr_id']}: {g['reasoning']}")
            entry_lines.extend(_drift_whats_new_lines(drifted_pages))
            entry_lines.extend(_citation_drift_whats_new_lines(citation_ledger))
            entry_lines.extend(_core_drift_whats_new_lines(core_drifted))
            entry = "\n".join(entry_lines) + "\n\n"
            existing = whats_new.read_text() if whats_new.exists() else ""
            whats_new.write_text(_compose_whats_new(existing, entry))

        # CCE-89 D1: capture the prior baseline BEFORE the promotion below
        # overwrites last_successful_run.head_sha. The PR-body composer
        # renders "baseline X → current Y" so the operator sees the review
        # window without opening state.json.
        prior_baseline_sha = state.get("last_successful_run", {}).get("head_sha", "")

        # CCE-40: promote current_run.head_sha into last_successful_run.
        # The merge of the docs-agent PR is what actually promotes this to
        # main; until then the advance lives only on the docs-agent branch
        # and on disk locally. If PR open fails, nothing reaches main and
        # the next run reads the unchanged committed state.
        # CCE-140: decide which deferred PRs this run abandons, BEFORE the
        # cursor walk — forgiveness is what lets the walk continue past them.
        # `counts` is the PRIOR map, so a stored count equal to the threshold
        # means this run is the (threshold+1)-th.
        #
        # CCE-151: hoisted out of `if time_truncated:`. It used to live inside
        # that branch, so a run that was merely DEGRADED — a page blocked by
        # lint, a page-author dispatch that returned nothing — fell through to
        # `advance_sha = head_sha` and walked the consume-once cursor straight
        # past a PR that had produced no documentation. Exit code 0, so nothing
        # alarmed. Observed twice in production on 2026-08-21 (runs
        # 32460602658, 32495019606) against theoju/claude-code-self-assessment;
        # the second advanced past the very page the first had stranded.
        #
        # Hoisting `partition_deferrals` WITH it is what keeps this safe rather
        # than catastrophic. Holding a PR back with no forgiveness path would
        # freeze the baseline the moment any page failed repeatedly — the
        # CCE-109 doom loop CCE-140 exists to prevent. The skip hatch is the
        # release valve, and it only arms because `still_deferred` now reaches
        # `next_deferral_counts` on this path too: it used to be left at its
        # `[]` default here, which silently CLEARED the count of every
        # held-back PR on every non-truncated run, so nothing could ever reach
        # the threshold.
        _deferral_counts = state.get("deferral_counts", {}) or {}
        _threshold = resolve_deferral_threshold(config)
        _deferred_all = list(admission_deferred) + [
            pr_by_number[n] for n in sorted(deferred_pages_by_pr) if n in pr_by_number
        ]
        _skipped_prs, _still_deferred = partition_deferrals(
            _deferred_all,
            counts=_deferral_counts,
            repo=repo,
            threshold=_threshold,
        )
        skipped_numbers = {p.get("number") for p in _skipped_prs}
        # CCE-140: hold every PR this run did not finish out of the cursor
        # prefix. On a run with no skips `skipped_numbers` is empty and
        # `held_back` is exactly "everything unfinished".
        held_back = (
            set(deferred_pages_by_pr) | {p.get("number") for p in admission_deferred}
        ) - skipped_numbers
        still_deferred = _still_deferred
        if time_truncated or held_back:
            # CCE-109 Component 4: never advance to a cursor we cannot confirm
            # is forward-of-baseline and reachable from HEAD, never advance
            # past an unanchorable deferred PR, and persist only the canonical
            # full SHA. Every refusal keeps the baseline — partial, retried
            # next run, but no silent regression and no lost PR.
            #
            # CCE-151: `or held_back` is the whole fix. Gating on that set
            # being non-empty rather than on `partial` is deliberate and
            # load-bearing — a run can be partial for reasons that cost no
            # content (an advisory agent that could not judge, a notifier that
            # could not post), and freezing the cursor for those reinstates the
            # doom loop. What must hold the baseline is unfinished CONTENT,
            # which is exactly what `held_back` names.
            advance_sha = prior_baseline_sha
            advance_cursor_backed = False
            cursor_prs = advance_cursor_list(
                prs, admission_deferred, held_back=held_back
            )
            cursor = _last_processed_merge_sha(cursor_prs)
            window = f"{(prior_baseline_sha or '(root)')[:8]}..{head_sha[:8]}"
            full_cursor = _rev_parse_commit(repo_root, cursor) if cursor else None
            # CCE-151: the walk now runs for two different causes, so the
            # reason has to name the one that actually applies. A run that was
            # never truncated reporting `time_budget_no_advance_*` would be a
            # false statement in the operator digest — and the digest is the
            # only place most of these are ever read. The `time_budget_` family
            # is preserved verbatim on the truncated path: those exact strings
            # are asserted by test_time_budget.py and test_deferral_skip.py,
            # and are what the CCE-109/CCE-140 runbooks tell operators to grep.
            _rsn = "time_budget" if time_truncated else "held_back"
            _kind = "truncated run" if time_truncated else "degraded run"
            if cursor is None:
                add_partial(
                    state,
                    f"{_rsn}_no_advance_no_cursor: {_kind} had no "
                    "admitted PR with a usable merge_sha; baseline unchanged",
                    degraded=True,
                )
            elif any(not (p.get("merge_sha") or "").strip() for p in still_deferred):
                add_partial(
                    state,
                    f"{_rsn}_no_advance_unanchored_deferred: a deferred "
                    f"PR has no merge_sha and would be stranded behind cursor "
                    f"{cursor[:8]}; baseline unchanged",
                    degraded=True,
                )
            elif full_cursor is None:
                add_partial(
                    state,
                    f"{_rsn}_advance_out_of_window: cursor {cursor[:8]} "
                    f"unresolvable in repo ({window}); baseline unchanged",
                    degraded=True,
                )
            else:
                ok, why = _sha_in_window(
                    full_cursor,
                    last_sha=prior_baseline_sha,
                    head_sha=head_sha,
                    repo_root=repo_root,
                )
                if ok:
                    advance_sha = full_cursor
                    # NOT equivalent to "advance_sha < head_sha". When every
                    # deferred PR has been forgiven by the skip hatch, the
                    # walk covers the whole window and the cursor can land on
                    # HEAD itself. That is honest rather than a leak: the
                    # forgiven PRs are recorded in `skipped_prs` and alarmed,
                    # so nothing crossed here is unaccounted for. The
                    # invariant the merge gate rests on is "the baseline moved
                    # only past PRs that landed or were deliberately
                    # abandoned" — not "the baseline stayed below HEAD".
                    advance_cursor_backed = True
                else:
                    add_partial(
                        state,
                        f"time_budget_advance_out_of_window: cursor "
                        f"{full_cursor[:8]} {why} ({window}); baseline unchanged",
                        degraded=True,
                    )
        else:
            advance_sha = state["current_run"]["head_sha"]
            # An untruncated run with nothing held back advances to the full
            # window HEAD.
            #
            # CCE-151: this branch is now reached ONLY when `held_back` is
            # empty, which is what keeps clean-run behaviour identical. That
            # matters — the alternative (always walk the cursor) would land the
            # baseline on the last PR's merge_sha even on a clean run, leaving
            # direct-push commits after it permanently outside every window.
            # Gating on emptiness buys the fix without paying that.
            advance_cursor_backed = False
            # Nothing was held back, so the walk would have covered the whole
            # window. The deferral-skip recorder below intersects against this
            # to decide which forgiven PRs the cursor actually crossed.
            cursor_prs = list(prs)
        global _LAST_ADVANCE_CURSOR_BACKED
        _LAST_ADVANCE_CURSOR_BACKED = advance_cursor_backed
        if _skipped_prs:
            # CCE-151: was `if time_truncated:`. `_skipped_prs` is now computed
            # on every path, and a forgiven PR must be alarmed and durably
            # recorded wherever the forgiveness happened — otherwise the skip
            # hatch could abandon content on an untruncated run with no entry
            # in `skipped_prs` and no digest line. On a clean run the list is
            # empty and this block is skipped exactly as before.
            #
            # CCE-140 / spec Decision 3. Record the loss loudly and durably.
            # The reason is deliberately NOT info_only: it is content the
            # pipeline chose to abandon, and `partial` is what routes it into
            # the notifier digest. It does not veto the merge — the skip only
            # takes effect if this run merges (see _MERGE_VETO_REASON_PREFIXES).
            # Only PRs the walk ACTUALLY crossed are abandoned. A forgiven PR
            # sitting behind an older still-deferred one is not passed by the
            # cursor, so announcing and durably recording its loss would be a
            # false alarm — and `skipped_prs` is append-only and deduped by
            # `pr`, so a false entry can never be corrected.
            _crossed = {p.get("number") for p in cursor_prs}
            _records = []
            for _pr_obj in _skipped_prs:
                if _pr_obj.get("number") not in _crossed:
                    continue
                _k = deferral_key(repo, _pr_obj.get("number"))
                _pages = sorted(
                    set(deferred_pages_by_pr.get(_pr_obj.get("number"), []))
                )
                _records.append(
                    {
                        "pr": _k,
                        "url": _pr_obj.get("url", ""),
                        "pages": _pages,
                        "deferrals": int(_deferral_counts.get(_k, 0)),
                        "skipped_at": now,
                    }
                )
                add_partial(
                    state,
                    f"deferral_skip: {_k} skipped after "
                    f"{int(_deferral_counts.get(_k, 0))} consecutive deferrals "
                    f"(threshold {_threshold}); pages="
                    + (", ".join(_pages) if _pages else "(none authored)"),
                    degraded=True,
                )
            merge_skipped_pr_records(state, _records)
        # CCE-140: prune and increment on EVERY run, not only a truncated one.
        # "Consecutive" is only meaningful if a run that PROCESSED a PR clears
        # its history, and the run that processes it is usually the clean one.
        # Gating this on `time_truncated` made a truncated/clean/truncated
        # alternation accumulate toward a skip for a PR the pipeline handled
        # successfully every other night, and left counts for PRs long past
        # the baseline orphaned in state.json forever.
        _prior_counts = state.get("deferral_counts", {}) or {}
        _next_counts = next_deferral_counts(
            _prior_counts,
            repo=repo,
            window_pr_numbers={
                p.get("number") for p in window_prs if p.get("number") is not None
            },
            still_deferred_numbers={
                p.get("number") for p in still_deferred if p.get("number") is not None
            },
        )
        if _next_counts:
            state["deferral_counts"] = _next_counts
        else:
            state.pop("deferral_counts", None)
        # CCE-159: same never-seed-empty contract as deferral_counts — a host
        # that reused nothing and summarized nothing keeps a state.json
        # byte-identical to its pre-CCE-159 content.
        _next_summaries = next_pr_summaries(
            _summary_cache,
            repo=repo,
            window_prs=window_prs,
            summary_by_number=_summary_by_number,
            fingerprint=_summary_fingerprint,
            now=datetime.now(timezone.utc),
        )
        if _next_summaries:
            state["pr_summaries"] = _next_summaries
        else:
            state.pop("pr_summaries", None)
        if _summaries_reused:
            # Advisory: the saving has to be visible in the digest, or the one
            # number that says whether this feature is working is invisible.
            add_partial(
                state,
                f"pr_summaries_reused: {_summaries_reused}/{len(window_prs)} "
                f"PRs served from cache, {_summaries_reused} pr-summarizer "
                "dispatches skipped",
                info_only=True,
            )
        if _should_advance_watermark(state):
            state["last_successful_run"] = {
                "head_sha": advance_sha,
                "completed_at": now,
            }
            if time_truncated:
                # CCE-43 guard support: record the window this truncated run
                # covered so a same-hour re-dispatch is recognized as already
                # processed (the cursor alone never equals HEAD).
                state["last_successful_run"]["window_head_sha"] = state["current_run"][
                    "head_sha"
                ]
        state["current_run"]["pr_number"] = None
        save_persistent_state(state_path, state)
        save_current_run(state_path, state)
        if no_pr:
            return _exit_code(state)
        branch = branch_name(now)
        gh = GhClient(repo_root)
        pr_number, pr_reasons = open_or_append_pr(
            repo_root,
            gh,
            branch=branch,
            now_iso=now,
            partial=state["current_run"]["partial"],
            partial_reasons=state["current_run"]["partial_reasons"],
            lens_paths=config.get("docs", {}).get("lens_paths") or None,
            baseline_sha=prior_baseline_sha,
            # Spec Component 6: on a truncated run the operator-facing window
            # must end at the cursor actually persisted, not the full HEAD
            # (advance_sha == HEAD whenever the run wasn't truncated).
            current_sha=advance_sha,
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
        )
        for reason, info_only in pr_reasons:
            add_partial(state, reason, info_only=info_only)
        if pr_number is None:
            save_persistent_state(state_path, state)
            save_current_run(state_path, state)
            # CCE-73: surface the recorded reasons to stderr before exit so
            # the workflow log carries the failure root cause without the
            # operator having to fetch state.json out-of-band. Redact
            # credential URLs in case any reason came from a code path that
            # bypassed _record_failure (e.g., add_partial called from drift
            # handlers).
            safe_reasons = [
                _redact_credentials(r) for r in state["current_run"]["partial_reasons"]
            ]
            emit_log(
                f"docs-agent: orchestrator exiting 1; partial_reasons={safe_reasons}"
            )
            return 1
        state["current_run"]["pr_number"] = pr_number
        save_persistent_state(state_path, state)
        save_current_run(state_path, state)

        # CCE-101: auto-merge gate. Runs on both PR paths (fresh create and
        # same-hour append) — the human-edit guard inside makes the append
        # path safe. deadline/clock are the CCE-109 budget objects.
        merge_settings = resolve_merge_settings(config)
        merge_outcome, merge_reasons = _maybe_auto_merge(
            gh,
            pr_number=pr_number,
            partial=state["current_run"]["partial"],
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
            merge_settings=merge_settings,
            build_workflow=config.get("publishing", {}).get("build_workflow"),
            ci_provider=config.get("publishing", {}).get("ci_provider"),
            deadline=deadline,
            clock=clock,
            advance_cursor_backed=advance_cursor_backed,
            blind=bool(state["current_run"].get("blind")),
            partial_reasons=tuple(state["current_run"]["partial_reasons"]),
        )
        for reason, info_only in merge_reasons:
            add_partial(state, reason, info_only=info_only)
        save_persistent_state(state_path, state)
        save_current_run(state_path, state)

        # Compose digest and dispatch notifier.
        digest = {
            "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
            "run_summary_bullets": [
                f"PR #{s.get('pr_number')}: {s.get('what_changed', '')}"
                for s in summaries
            ],
            "gap_flags": [
                {"pr_id": v["pr_id"], "reasoning": v["reasoning"]}
                for v in gap_verdicts
                if v.get("needs_spec")
            ],
            "lint_failures": state["current_run"]["partial_reasons"],
            "partial_reasons": state["current_run"]["partial_reasons"],
            "source_drift": drifted_pages,
            "citation_drift": citation_ledger,
            "core_drift": core_drifted,
            "fact_check_warnings": state["current_run"].get("fact_check_warnings")
            or [],
            "merge_outcome": merge_outcome,
        }
        notifier_result, reasons = dispatch_validated(
            "notifier",
            {
                "digest": digest,
                "slack_config": config.get("notifications", {}).get("slack", {}),
                "email_config": config.get("notifications", {}).get("email", {}),
                "mode": "run",
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        _record_dispatch_reasons(state, reasons, ok=notifier_result is not None)
        if notifier_result is None:
            if not reasons:
                add_partial(state, "notifier_invalid: returned None", degraded=False)
            save_persistent_state(state_path, state)
            save_current_run(state_path, state)
        return _exit_code(state)
    finally:
        try:
            _emit_shutdown_dump(state)
        except OSError as exc:
            emit_log(f"docs-agent: _emit_shutdown_dump failed: {exc}")
        _write_step_summary(state, repo_root)


def run_bootstrap_core(
    repo_root: Path,
    *,
    dry_run_dir: Path | None,
    today: str | None = None,
) -> int:
    """C2 bootstrap authoring entry. Reads <docs_dir>/.doc-core-manifest.json and
    authors each declared core page that has no file yet, via the unchanged
    page-author agent. Idempotent (create-missing only), diagram-free, best-effort
    per page (a dispatch failure or post-write verification failure records a
    reason and continues; the rejected file is deleted so re-run retries it).
    No-op when there is no config docs_dir, no manifest, or an empty manifest.
    Returns 0 on success/no-op, 2 on unreadable config. Prints a JSON ledger
    to stdout.

    Post-write verification (CCE-38): after each dispatch the orchestrator
    re-parses the frontmatter the agent wrote and runs
    ``description_quality.check_fm`` against it. Bad YAML, missing frontmatter,
    or a thin description rejects the page (file deleted, reason recorded).
    """
    import frontmatter_contract as fmc
    import archive_indexes

    _lint_dir = str(Path(__file__).resolve().parent / "lint")
    if _lint_dir not in sys.path:
        sys.path.insert(0, _lint_dir)
    import description_quality

    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    if not cfg_path.exists():
        emit_log("no config")
        return 2
    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        emit_log(f"config invalid: {e}")
        return 2

    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        emit_log("no docs_dir; nothing to bootstrap")
        return 0

    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        emit_log("no core manifest; run setup first")
        return 0
    pages = _load_core_manifest_pages(repo_root, docs_dir)
    if not pages:
        return 0

    today = today or datetime.now(timezone.utc).date().isoformat()
    voice_samples = load_voice_samples(repo_root, config)
    editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
    section = next(
        (
            s
            for s in ((config.get("site") or {}).get("sections") or [])
            if isinstance(s, dict) and s.get("generator") == "agent-authored"
        ),
        None,
    )
    lens = (section or {}).get("key") or "core"

    def _check(target_path: Path, page: dict) -> tuple[bool, list[str]]:
        if not target_path.exists():
            # Dry-run path: _synthesize_core_page writes the body after dispatch
            # returns. The integration tests cover the synth case separately.
            return True, []
        try:
            rel_inner = (
                target_path.resolve().relative_to(repo_root.resolve()).as_posix()
            )
        except ValueError:
            rel_inner = target_path.as_posix()
        try:
            fm = archive_indexes.parse_frontmatter_strict(target_path.read_text())
        except yaml.YAMLError as e:
            # str(e) carries line/column from the YAML parser when present
            # (e.g., yaml.scanner.ScannerError formats to a multi-line trace);
            # collapse newlines so the ledger stays single-line per reason.
            return False, [
                f"frontmatter_parse_error: {rel_inner}: {str(e).replace(chr(10), ' | ')}"
            ]
        except ValueError:
            return False, [f"frontmatter_missing: {rel_inner}"]
        ok, msg = description_quality.check_fm(
            fm, title=page.get("title"), config=config
        )
        if not ok:
            return False, [f"description_quality: {rel_inner}: {msg}"]
        return True, []

    progress = _BootstrapProgress(repo_root, total=len(pages))
    progress.start()

    ledger: dict = {"authored": [], "skipped_existing": [], "reasons": []}
    try:
        for idx, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or "page" not in page:
                reason = "manifest_page_invalid"
                ledger["reasons"].append(reason)
                # Synthetic identifier — the entry has no usable path, so we
                # tag it by its manifest position so current_index still
                # advances and the failure shows up in the progress file.
                placeholder = f"<manifest_entry_{idx}>"
                progress.begin_page(placeholder)
                progress.mark_failed(placeholder, reason=reason)
                continue
            target_path = repo_root / docs_dir / page["page"]
            try:
                rel_posix = (
                    target_path.resolve().relative_to(repo_root.resolve()).as_posix()
                )
            except ValueError:
                reason = f"unsafe_page_path: {page['page']}"
                ledger["reasons"].append(reason)
                placeholder = str(page["page"])
                progress.begin_page(placeholder)
                progress.mark_failed(placeholder, reason=reason)
                continue
            if not _page_target_is_editable(rel_posix, editable_globs):
                reason = f"unsafe_page_path: {rel_posix}"
                ledger["reasons"].append(reason)
                progress.begin_page(rel_posix)
                progress.mark_failed(rel_posix, reason=reason)
                continue
            if target_path.exists():
                ledger["skipped_existing"].append(rel_posix)
                # begin_page first so current_index advances through every
                # manifest entry (skipped or authored); mark_skipped's
                # contract assumes begin_page has already run.
                progress.begin_page(rel_posix)
                progress.mark_skipped(rel_posix)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            progress.begin_page(rel_posix)
            out, reasons = dispatch_verified(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": "create",
                    "lens": lens,
                    "summaries": [],
                    "voice_samples": voice_samples,
                    "frontmatter_template": fmc.agent_authored_frontmatter_dict(
                        description=page.get("title") or page.get("key") or "",
                        source_files=page.get("source_files") or [],
                        last_reviewed=today,
                        status="draft",
                    ),
                    "manifest_page": page,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
                post_write_check=_check,
                target_path=target_path,
                manifest_page=page,
            )
            ledger["reasons"].extend(reasons)
            if out is None:
                fallback = f"page_author_invalid: {rel_posix}"
                if not reasons:
                    ledger["reasons"].append(fallback)
                progress.mark_failed(
                    rel_posix, reason=reasons[-1] if reasons else fallback
                )
                continue
            if out.get("ok"):
                if dry_run_dir and not target_path.exists():
                    _synthesize_core_page(target_path, page, today)
                ledger["authored"].append(rel_posix)
                progress.mark_completed(rel_posix)
            else:
                err = out.get("error") or "page-author returned ok=false"
                msg = f"page_author_error: {rel_posix}: {err}"
                ledger["reasons"].append(msg)
                progress.mark_failed(rel_posix, reason=msg)
    finally:
        progress.finish()

    print(json.dumps(ledger, indent=2))
    return 0


def branch_name(now_iso: str) -> str:
    return f"docs-agent/{now_iso[:13]}"


def _remote_state_covers_window(remote_state: dict, our_head_sha: str) -> bool:
    """True if a committed state.json shows the window ending at
    ``our_head_sha`` was already processed.

    A full run records ``last_successful_run.head_sha == HEAD``; a
    time-truncated run (CCE-109) records a mid-window cursor there plus
    ``window_head_sha == HEAD``. Either field matching means this hour's
    window was already (at least partially) processed — without the second
    field, every truncated run would defeat the CCE-43 guard and a same-hour
    re-dispatch would die on the CCE-42 layer-3 checkout refusal.
    """
    lsr = remote_state.get("last_successful_run") or {}
    heads = {lsr.get("head_sha", ""), lsr.get("window_head_sha", "")}
    heads.discard("")
    return bool(our_head_sha) and our_head_sha in heads


def _remote_already_processed_window(
    repo_root: Path, branch: str, our_head_sha: str
) -> bool:
    """True if origin/<branch>'s committed state.json shows it already
    advanced last_successful_run.head_sha to our_head_sha. In that case the
    docs-agent branch already holds the run we're about to redo, and
    proceeding would only collide on whats-new.md / state.json at checkout
    (the CCE-42 layer-3 failure mode).

    Every failure mode (fetch failure, missing state.json, JSON parse error,
    schema drift) returns False so the runner proceeds normally — false
    positives would silently skip real work; false negatives just produce
    the existing checkout_failed partial reason that operators already know
    how to resolve.
    """
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", branch],
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        return False
    show = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show",
            f"origin/{branch}:.engineering-docs-agent/state.json",
        ],
        capture_output=True,
        text=True,
    )
    if show.returncode != 0:
        return False
    try:
        remote = json.loads(show.stdout)
        return _remote_state_covers_window(remote, our_head_sha)
    except (json.JSONDecodeError, AttributeError):
        return False


def _format_partial_digest(partial_reasons: list[str], *, partial: bool = True) -> str:
    """Single-source format for partial_reasons.

    Used by:
    - PR body composer in open_or_append_pr
    - GITHUB_STEP_SUMMARY writer in _write_step_summary

    Returns an empty string when partial_reasons is empty so callers
    can detect the no-reasons case without re-checking the list.

    CCE-121: the header reflects the run's ``partial`` FLAG, not merely the
    presence of reasons. Since CCE-118, ``partial_reasons`` also carries
    ``info_only`` advisory reasons (benign prose-contamination rescues) that
    do NOT flip ``partial`` — so a non-partial run renders those under an
    INFO header, never the "Partial run" warning (which would mislabel a clean,
    auto-merged run). ``partial`` defaults to True for back-compat with callers
    that predate the flag. Mirrors the PARTIAL/INFO split in _emit_exit_summary.
    """
    if not partial_reasons:
        return ""
    header = (
        "WARNING — Partial run"
        if partial
        else "INFO — advisory notices (run not partial)"
    )
    lines = [header, ""]
    lines.extend(f"- {r}" for r in partial_reasons)
    return "\n".join(lines)


def _bucket_files_by_lens(
    files: list[str], lens_paths: dict[str, str]
) -> dict[str, int]:
    """Bucket file paths into lens-name counts, longest-prefix-match wins.

    Files outside every lens land in the `other` bucket. Output ordering
    is lens_paths-declaration order followed by `other` (deterministic for
    PR-body rendering).
    """
    if not files:
        return {}
    # Sort lens entries by descending path-length so a narrower lens
    # (docs/site-src/architecture/) wins over the broader parent
    # (docs/site-src/) on files under the narrower path.
    sorted_lenses = sorted(lens_paths.items(), key=lambda kv: -len(kv[1]))
    counts: dict[str, int] = {name: 0 for name in lens_paths}
    counts["other"] = 0
    for f in files:
        bucket = "other"
        for lens_name, lens_path in sorted_lenses:
            if f.startswith(lens_path):
                bucket = lens_name
                break
        counts[bucket] += 1
    # Drop zero-count buckets for compact rendering.
    return {k: v for k, v in counts.items() if v > 0}


def _compose_pr_body(
    *,
    changed_files: list[str],
    lens_paths: dict[str, str] | None,
    partial: bool,
    partial_reasons: list[str],
    baseline_sha: str,
    current_sha: str,
    top_n: int = 5,
    fact_warnings: list[str] | None = None,
) -> str:
    """CCE-89 D1: compose a docs-agent PR body with operator-review enrichment.

    Sections (each conditional on input):
      - Review window header — baseline + current head SHAs.
      - Files by lens — count per lens_name + an `other` bucket.
      - Top-N changed pages — capped at top_n, with a `(+M more)` truncation
        note when more files changed than the cap.
      - Partial-reasons digest — `_format_partial_digest` output appended last.

    Back-compat: with no enrichment data passed (all defaults), returns the
    legacy `"docs-agent run"` sentinel so callers that don't yet thread the
    new args don't render a body of empty sections.

    Partial-only path: with only `partial_reasons` populated, returns the
    bare digest — same shape as pre-CCE-89 partial PR bodies, so unit tests
    that exercise the partial path keep passing.
    """
    has_files = bool(changed_files)
    has_baseline = bool(baseline_sha) and bool(current_sha)
    has_reasons = bool(partial_reasons)
    has_warnings = bool(fact_warnings)

    if not has_files and not has_baseline and not has_reasons and not has_warnings:
        return "docs-agent run"

    if not has_files and not has_baseline and has_reasons and not has_warnings:
        return _format_partial_digest(partial_reasons, partial=partial)

    sections: list[str] = []

    if has_baseline:
        sections.append(
            f"**Review window:** baseline `{baseline_sha[:8]}` → "
            f"current `{current_sha[:8]}`"
        )

    if has_files and lens_paths:
        counts = _bucket_files_by_lens(changed_files, lens_paths)
        if counts:
            rendered = ", ".join(f"{name}: {n}" for name, n in counts.items())
            sections.append(f"**Files by lens:** {rendered}")

    if has_files:
        top = changed_files[:top_n]
        remaining = len(changed_files) - len(top)
        page_lines = [f"**Top {len(top)} changed pages:**"]
        page_lines.extend(f"- `{f}`" for f in top)
        if remaining > 0:
            page_lines.append(f"- _(+{remaining} more)_")
        sections.append("\n".join(page_lines))

    if has_warnings:
        warn_lines = ["**Factual-accuracy warnings:**"]
        warn_lines.extend(f"- {w}" for w in fact_warnings)
        sections.append("\n".join(warn_lines))

    if has_reasons:
        digest = _format_partial_digest(partial_reasons, partial=partial)
        if digest:
            sections.append(digest)

    return "\n\n".join(sections) + "\n"


def _emit_shutdown_dump(state: dict) -> None:
    """Emit a one-reason-per-line stderr summary of partial_reasons.

    Called from run()'s finally block BEFORE _write_step_summary. Covers
    the exit-0 partial run case (notifier completes, PR opens with
    WARNING-Partial digest, run returns 0 — currently no log signal)
    AND fires again on exit-1 alongside the existing pre-finally dump
    at line 1412 (belt-and-suspenders).

    Gating: non-empty `state['current_run']['partial_reasons']`. NOT
    gated on `partial` — info_only reasons still warrant exit-time
    visibility. Matches the precedent at _write_step_summary (gates on
    reasons list, not partial flag).

    Prefix policy (Open Question Option (a) — locked):
      - PARTIAL for all reasons when state['current_run']['partial'] is True
        (the common case: any non-info_only reason has flipped it).
      - INFO for all reasons when partial is False (info_only-only run).
    Per-reason PARTIAL vs INFO granularity is visible only in the per-call
    emit during the run, never in the shutdown dump.

    Implementation: uses print() directly, NOT emit_stderr/emit_log,
    so OSError propagates to the caller. emit_stderr/emit_log are
    best-effort (OSError-swallowed); the shutdown dump is the operator's
    last-resort observability signal and must fail loudly if stderr is
    broken. Still calls _redact_credentials per reason for defense-in-depth
    (reasons are already redacted at add_partial entry, but a future
    contributor bypassing add_partial cannot leak via the shutdown dump).
    """
    cr = state.get("current_run") or {}
    reasons = cr.get("partial_reasons") or []
    if not reasons:
        return
    prefix = "PARTIAL" if cr.get("partial") else "INFO"
    print(
        f"docs-agent: run exit summary (reasons={len(reasons)}):",
        file=sys.stderr,
        flush=_OBSERVABILITY_FLUSH,
    )
    for r in reasons:
        safe = _redact_credentials(r)
        print(
            f"docs-agent {prefix}: {safe}",
            file=sys.stderr,
            flush=_OBSERVABILITY_FLUSH,
        )


def _write_step_summary(state: dict, repo_root: Path) -> None:
    """Append the partial-reasons digest to $GITHUB_STEP_SUMMARY.

    No-op when the env var is unset (local runs, unit tests), when
    state lacks current_run, or when partial_reasons is empty.

    Failure-tolerant: never raises. If the path is unwritable
    (read-only fs, missing parent), swallows the OSError and returns —
    the runner's primary job is producing docs, not diagnostics.
    """
    summary_path_str = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path_str:
        return
    cr = state.get("current_run") or {}
    reasons = cr.get("partial_reasons") or []
    if not reasons:
        return
    digest = _format_partial_digest(reasons, partial=bool(cr.get("partial")))
    if not digest:
        return
    section = "\n## docs-agent partial_reasons\n\n" + digest + "\n"
    try:
        with open(summary_path_str, "a", encoding="utf-8") as fh:
            fh.write(section)
    except OSError:
        # Best-effort. The workflow's `if: always()` state.json cat
        # step still runs; this digest is additive context.
        return


def _stage_docs_run_changes(repo_root: Path) -> tuple[int, str]:
    """Stage all run-emitted changes in `repo_root`, excluding the vendored
    plugin checkout at `.docs-agent-plugin/`.

    The host's workflow checks out the plugin into `.docs-agent-plugin/`
    via actions/checkout (see templates/workflow-run.yml). Two host layouts
    are handled uniformly here:

    - Hosts where `.docs-agent-plugin/` is NOT gitignored: `git add -A .`
      stages the nested actions/checkout as a submodule gitlink (mode
      160000). The follow-up `git restore --staged` reverts the index
      entry to match HEAD (which has nothing at this path) — CCE-70.
    - Hosts where `.docs-agent-plugin/` IS gitignored (e.g. ADIS): git's
      tree walk silently skips it during `git add -A`; the diff check
      finds nothing staged under that path, so the restore step is
      skipped — CCE-75.

    `git restore --staged` (rather than `git rm --cached`) is used so
    that if a host has unrelated tracked content at `.docs-agent-plugin/`
    — a real submodule registration in `.gitmodules`, or files committed
    before the plugin was adopted — restore preserves them (it reverts
    the index to match HEAD, not deletes from the index).

    The prior implementation used a negative pathspec
    (`:!.docs-agent-plugin`), which collided with host `.gitignore`
    entries: naming a path in a pathspec promotes it to "explicitly
    mentioned", which triggers git's gitignore-aware safety check —
    failing with `paths are ignored by one of your .gitignore files`.

    Mid-run modifications to tracked content under `.docs-agent-plugin/`
    are dropped from the docs commit: `git add -A .` stages them, the
    diff probe then sees the staged change under `.docs-agent-plugin/`
    and TRIGGERS the `git restore --staged --` step (which is gated on
    the probe finding anything — not unconditional), and the restore
    reverts the index entry back to HEAD. Docs runs should never mutate
    the plugin tree on the runner, so this is correct — but it does
    mean an orchestrator bug that touched plugin files would fail
    silently in the docs PR. (Pinned by tests in
    `tests/orchestrator/test_gitlink_exclusion.py`.)
    """
    # The three git operations below all assume `.docs-agent-plugin/`
    # is a real directory (per actions/checkout@v5), not a symlink.
    # A symlink would change pathspec semantics for add/diff/restore
    # alike: `add -A .` would recurse into the target, and the diff
    # probe + restore would match the link rather than its contents.
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "-A", "."],
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        return add.returncode, add.stderr.strip()

    diff = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--cached",
            "--name-only",
            "--",
            ".docs-agent-plugin",
        ],
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        return diff.returncode, diff.stderr.strip()
    if not diff.stdout.strip():
        return 0, ""

    restore = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "restore",
            "--staged",
            "--",
            ".docs-agent-plugin",
        ],
        capture_output=True,
        text=True,
    )
    if restore.returncode != 0:
        return restore.returncode, restore.stderr.strip()
    return 0, ""


def _record_failure(
    reasons: list[tuple[str, bool]], reason: str, *, info_only: bool = False
) -> None:
    """Append (reason, info_only) to reasons AND emit it to stderr.

    CCE-73: every failure path in open_or_append_pr previously captured
    subprocess stderr into state.partial_reasons but emitted zero bytes to
    stdout/stderr. Combined with Python's block-buffered stdout under GitHub
    Actions, a crash in any failure branch produced a workflow log of just
    `Process completed with exit code 1`. The stderr emit makes the reason
    greppable in the raw log alongside being persisted to state.json.
    """
    safe = _redact_credentials(reason)
    print(f"docs-agent: open_or_append_pr {safe}", file=sys.stderr, flush=True)
    reasons.append((safe, info_only))


_DOCS_AGENT_BOT_AUTHOR_NAMES = (
    "engineering-docs-agent[bot]",
    "engineering-docs-agent-bot",
)
_DOCS_AGENT_BOT_AUTHOR_EMAILS = ("engineering-docs-agent@users.noreply.github.com",)


def _commit_author_is_bot(
    author: dict,
    bot_names: tuple[str, ...],
    bot_emails: tuple[str, ...],
) -> bool:
    """A commit author qualifies as the docs-agent bot when name / login /
    email matches any configured bot identity. Conservative — any single
    match counts so GH's mixed name/login conventions don't false-positive.
    """
    name = (author.get("name") or "").strip()
    login = (author.get("login") or "").strip()
    email = (author.get("email") or "").strip().lower()
    if name in bot_names or login in bot_names:
        return True
    if email in tuple(e.lower() for e in bot_emails):
        return True
    return False


def _auto_close_superseded_docs_agent_prs(
    gh: "GhClient",
    *,
    new_pr_number: int,
    new_pr_branch: str,
    bot_author_names: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_NAMES,
    bot_author_emails: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_EMAILS,
) -> list[tuple[str, bool]]:
    """CCE-89 D2: close prior open docs-agent/* PRs superseded by the new one.

    Policy: each nightly opens a fresh ``docs-agent/YYYY-MM-DDTHH`` branch,
    never an append-commit. Any prior open docs-agent/* PR is superseded by
    definition. The only exception is a PR with human-authored commits —
    those stay open for human resolution.

    Returns ``[(reason, info_only)]`` for the caller's add_partial loop. ALL
    reasons are ``info_only=True`` — auto-close is cosmetic hygiene; its
    failures must not flip the run to partial (the partial flag stays
    driven by the authoring pipeline).
    """
    reasons: list[tuple[str, bool]] = []

    listing = gh.pr_list_docs_agent_open()
    if not listing.ok:
        reasons.append((f"auto_close_list_failed: {listing.error}", True))
        return reasons

    for pr_info in listing.value or []:
        prior_num = pr_info.get("number")
        prior_branch = pr_info.get("headRefName", "")
        if prior_num is None or prior_num == new_pr_number:
            continue

        # Human-edit guard: any non-bot commit → skip auto-close.
        commits = gh.pr_view_commits(prior_num)
        if not commits.ok:
            reasons.append(
                (
                    f"auto_close_skipped:{prior_num}:commits_lookup_failed: "
                    f"{commits.error}",
                    True,
                )
            )
            continue

        any_human = False
        for commit in commits.value or []:
            for author in commit.get("authors") or []:
                if not _commit_author_is_bot(
                    author, bot_author_names, bot_author_emails
                ):
                    any_human = True
                    break
            if any_human:
                break

        if any_human:
            reasons.append(
                (
                    f"auto_close_skipped:{prior_num}:human_edited: "
                    f"branch={prior_branch}",
                    True,
                )
            )
            continue

        # All-bot PR → close with the exact spec comment.
        comment = (
            f"Auto-closing: superseded by #{new_pr_number} "
            f"(docs-agent freshest-only policy)"
        )
        close = gh.pr_close(prior_num, comment)
        if close.ok:
            reasons.append(
                (
                    f"auto_close_succeeded:{prior_num}: branch={prior_branch}",
                    True,
                )
            )
        else:
            reasons.append((f"auto_close_failed:{prior_num}: {close.error}", True))

    return reasons


# CCE-140: partial reasons that veto auto-merge even on a cursor-backed
# advance. The cursor proves the BASELINE is honest; it says nothing about
# whether this PR is safe to land. `app_token_unavailable` is recorded as a
# blocking reason at :1377 for exactly this purpose (README §nightly): a PR
# built on the fallback GITHUB_TOKEN never fires host CI, so `gh pr checks`
# returns [] and the zero-checks branch below would read that as green.
# Match is by prefix, against the reason string as stored in state.
#
# `deferral_skip:` is deliberately NOT here — a skip only happens on a
# truncated run and only takes effect if that run merges.
_MERGE_VETO_REASON_PREFIXES: tuple[str, ...] = ("app_token_unavailable",)


def merge_veto_reason(partial_reasons) -> str | None:
    """Return the first veto prefix present in ``partial_reasons``, else None."""
    for reason in partial_reasons or ():
        for prefix in _MERGE_VETO_REASON_PREFIXES:
            if reason.startswith(prefix):
                return prefix
    return None


def _maybe_auto_merge(
    gh: "GhClient",
    *,
    pr_number: int,
    partial: bool,
    fact_warnings: list[str],
    merge_settings: dict,
    build_workflow: str | None,
    ci_provider: str | None = None,
    deadline: float | None,
    clock: Callable[[], float],
    sleep: Callable[[float], None] = time.sleep,
    bot_author_names: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_NAMES,
    bot_author_emails: tuple[str, ...] = _DOCS_AGENT_BOT_AUTHOR_EMAILS,
    advance_cursor_backed: bool = False,
    blind: bool = False,
    partial_reasons: tuple[str, ...] = (),
) -> tuple[dict, list[tuple[str, bool]]]:
    """CCE-101: squash-merge the docs-agent PR when the run earned it.

    Eligibility (cheapest first): policy auto → no vetoing partial reason →
    non-partial OR a cursor-backed advance → no human commits on the PR →
    enough CCE-109 budget left to wait out the check-grace window. Then a
    bounded poll of `gh pr checks`; zero registered checks after the grace
    window means a no-App-token host (the in-run validation is the gate
    there).

    CCE-140: `partial` alone no longer blocks. Every run this pipeline has
    ever produced is partial, so the unconditional block meant the auto-merge
    path never once fired on the flagship host and ten PRs were merged by
    hand until the human stopped. `advance_cursor_backed` is the replacement
    invariant: True only when advance_sha was assigned from a cursor that
    passed `_sha_in_window`, i.e. the baseline moves by exactly the PRs whose
    pages all landed.

    CCE-144: `blind` skips unconditionally, ahead of the CCE-140 carve-out.
    A cursor-backed advance proves the baseline is honest about what the run
    SAW; a blind run did not see. The reachable case is a time-truncated run
    (advance_cursor_backed=True) whose content-validator dispatch returned
    None — blind, partial, and cursor-backed at once, matching no entry in
    _MERGE_VETO_REASON_PREFIXES.

    `blind` is read here before `notifier_invalid` is recorded, so a run
    blind ONLY because its digest dispatch failed will already have merged
    by the time that reason lands — deliberately, since a failed digest
    means the operator was not told while the authoring work itself
    completed, and the merge is honest. The alarm is not lost: `_exit_code`
    reads `blind` at the end of `run`, so the run still exits 1 and still
    goes red.

    Fact-checker warnings are NOT an eligibility input (CCE-140 / spec
    Decision 4). They ride the PR body, the digest, and the notification.
    `fact_warnings` is retained in the signature only so the caller's kwargs
    and the digest composition need no change.

    Returns (merge_outcome, reasons): merge_outcome is the digest's
    ``{"merged": bool, "reason": str | None}``; reasons feed the caller's
    add_partial loop and are ALL info_only=True — merge automation is
    hygiene (mirrors D2 auto-close), it never flips the run to partial.
    """

    def skip(key: str, detail: str = "") -> tuple[dict, list[tuple[str, bool]]]:
        msg = f"auto_merge_skipped: {key}"
        if detail:
            msg += f": {detail}"
        return {"merged": False, "reason": key}, [(msg, True)]

    if merge_settings.get("policy") != "auto":
        # The configured normal path for a manual host — no reason entry,
        # the digest's merge_outcome line carries it.
        return {"merged": False, "reason": "policy_manual"}, []
    veto = merge_veto_reason(partial_reasons)
    if veto:
        return skip("merge_vetoed", veto)
    if blind:
        # CCE-144. Ahead of the CCE-140 carve-out below on purpose: a
        # cursor-backed advance is not evidence for a run that was prevented
        # from judging. Gating on the computed flag rather than extending
        # _MERGE_VETO_REASON_PREFIXES closes the whole class of blind reasons
        # instead of one hand-listed member of it.
        return skip("blind_run")
    if partial and not advance_cursor_backed:
        # CCE-140 / spec Decision 2. A partial run whose advance came from the
        # CCE-109 cursor has, by construction, advanced only past PRs whose
        # pages all landed; its reverted pages stay in-window and are
        # re-authored next run. A partial run that would advance to FULL HEAD
        # has not — merging it promotes the baseline past work that was never
        # authored, which is the silent-loss bug, automated nightly.
        return skip("partial_run")

    # Human-edit guard (same authority as D2 auto-close): run it on both
    # PR paths — on a fresh PR every commit is the bot's, so the extra
    # lookup is one cheap gh call for one uniform code path.
    commits = gh.pr_view_commits(pr_number)
    if not commits.ok:
        return skip("commits_lookup_failed", commits.error or "")
    for commit in commits.value or []:
        for author in commit.get("authors") or []:
            if not _commit_author_is_bot(author, bot_author_names, bot_author_emails):
                return skip("human_edited")

    grace = merge_settings["checks_grace_seconds"]
    timeout = merge_settings["checks_timeout_seconds"]
    # CCE-140: the CCE-109 run deadline governs the AUTHORING work — the
    # expensive, interruptible part. It must not govern the merge epilogue,
    # because the only run that can be cursor-backed is a time-truncated one,
    # and a time-truncated run is BY DEFINITION already past `deadline`.
    # Enforcing it here refuses every run this feature exists to merge: the
    # gate three lines up opens, and this check closes it — the original
    # never-auto-merges bug, one layer deeper and just as silent.
    #
    # The epilogue stays bounded, by the operator's own grace/timeout config
    # measured from now instead of by the spent authoring budget. Operator
    # consequence: a run that earns a merge may exceed `time_budget_seconds`
    # by up to `merge.checks_timeout_seconds` (default 900s) while it waits
    # out host CI. That is the designed cost of auto-merge on the
    # non-truncated path already; CCE-140 makes the truncated path pay it too
    # rather than forfeit the merge.
    merge_deadline = None if advance_cursor_backed else deadline
    if merge_deadline is not None and clock() + grace > merge_deadline:
        return skip("time_budget")

    start = clock()
    grace_end = start + grace
    poll_end = start + timeout
    if merge_deadline is not None:
        poll_end = min(poll_end, merge_deadline)

    while True:
        checks = gh.pr_checks(pr_number)
        if not checks.ok:
            return skip("checks_query_failed", checks.error or "")
        items = checks.value or []
        red = [
            c
            for c in items
            if c.get("state") == "FAILURE" or c.get("bucket") in ("fail", "cancel")
        ]
        if red:
            names = ",".join(sorted(c.get("name") or "?" for c in red))
            return skip("checks_failed", names)
        pending = [
            c
            for c in items
            if not (
                c.get("state") == "SUCCESS" or c.get("bucket") in ("pass", "skipping")
            )
        ]
        now = clock()
        if not items:
            if now >= grace_end:
                break  # zero checks registered: in-run validation is the gate
        elif not pending:
            break  # every registered check settled green
        if now >= poll_end:
            return skip(
                "checks_timeout", f"{len(pending)} pending after {int(now - start)}s"
            )
        sleep(_CHECKS_POLL_INTERVAL_SECONDS)

    merged = gh.pr_merge(pr_number)
    if not merged.ok:
        return (
            {"merged": False, "reason": "merge_failed"},
            [(f"auto_merge_failed: {merged.error}", True)],
        )
    reasons: list[tuple[str, bool]] = [(f"auto_merge_succeeded: pr={pr_number}", True)]
    provider = ci_provider or "github"
    if provider == "github":
        if build_workflow:
            dispatch = gh.workflow_run(build_workflow)
            if dispatch.ok:
                reasons.append((f"pages_dispatch_succeeded: {build_workflow}", True))
            else:
                reasons.append((f"pages_dispatch_failed: {dispatch.error}", True))
    else:
        # CCE-123: non-github providers degrade honestly — no GH Actions dispatch,
        # one info_only reason. Real trigger stubbed behind UNVALIDATED_AGAINST_LIVE_HOST.
        _triggered, trigger_reasons = resolve_build_trigger(provider)
        for r in trigger_reasons:
            reasons.append((f"pages_dispatch_skipped: {r}", True))
    return {"merged": True, "reason": None}, reasons


def _changed_files_in_head_commit(repo_root: Path) -> list[str]:
    """Return repo-relative paths committed by the most recent commit.

    Empty list on any failure (no parent commit, git binary missing,
    detached HEAD with no commits). The body-enrichment caller treats
    the empty case as "no enrichment data available" and falls back
    gracefully.
    """
    try:
        r = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "diff",
                "--name-only",
                "HEAD~1",
                "HEAD",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def open_or_append_pr(
    repo_root: Path,
    gh: GhClient,
    *,
    branch: str,
    now_iso: str,
    partial: bool,
    partial_reasons: list[str],
    lens_paths: dict[str, str] | None = None,
    baseline_sha: str = "",
    current_sha: str = "",
    fact_warnings: list[str] | None = None,
) -> tuple[int | None, list[tuple[str, bool]]]:
    """Open or append the docs-agent PR for `branch`.

    Returns (pr_number_or_None, reasons) where reasons is a list of
    (reason_string, info_only_bool) pairs the caller should pass to add_partial.
    """
    reasons: list[tuple[str, bool]] = []

    # CCE-42: fetch the remote branch first so same-hour reruns base their
    # local branch on the existing remote tip — append-commit semantics per
    # agents/engineering-docs-agent.md ("If a branch with that name exists
    # AND has an open PR: git checkout it, add the new commits, git push.
    # Append-commit, no force-push."). Without this fetch, `git checkout -B`
    # would reset the local branch to HEAD (main) and the subsequent push
    # would fail non-fast-forward against any existing remote SHA.
    fetch = subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", branch],
        capture_output=True,
        text=True,
    )
    checkout_argv = ["git", "-C", str(repo_root), "checkout", "-B", branch]
    if fetch.returncode == 0:
        checkout_argv.append(f"origin/{branch}")
    checkout = subprocess.run(checkout_argv, capture_output=True, text=True)
    if checkout.returncode != 0:
        _record_failure(
            reasons, f"checkout_failed: {checkout.stderr.strip()[:_STDERR_TRUNCATE]}"
        )
        return None, reasons

    add_rc, add_stderr = _stage_docs_run_changes(repo_root)
    if add_rc != 0:
        _record_failure(reasons, f"git_add_failed: {add_stderr[:_STDERR_TRUNCATE]}")
        return None, reasons

    commit_msg = f"docs(agent): run {now_iso}"
    if partial:
        commit_msg += " (partial)"
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", commit_msg], check=False
    )

    push = subprocess.run(
        ["git", "-C", str(repo_root), "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        local_head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        lsremote = subprocess.run(
            ["git", "-C", str(repo_root), "ls-remote", "origin", branch],
            capture_output=True,
            text=True,
        )
        remote_sha = ""
        if lsremote.returncode == 0 and lsremote.stdout.strip():
            remote_sha = lsremote.stdout.split()[0]
        local_sha = local_head.stdout.strip()

        stderr_summary = (push.stderr or "").strip()[:_STDERR_TRUNCATE]
        if local_head.returncode != 0 or not local_sha:
            _record_failure(
                reasons,
                f"push_failed_unknown: rev-parse failed (rc={local_head.returncode}); "
                f"push stderr: {stderr_summary}",
            )
            return None, reasons
        if remote_sha == local_sha:
            _record_failure(
                reasons,
                f"push_tracking_setup_failed: {stderr_summary}",
                info_only=True,
            )
        elif lsremote.returncode != 0:
            _record_failure(
                reasons,
                f"push_failed_unknown: ls-remote rc={lsremote.returncode}; "
                f"push stderr: {stderr_summary}",
            )
            return None, reasons
        else:
            _record_failure(reasons, f"push_refs_failed: {stderr_summary}")
            return None, reasons

    existing = gh.pr_list_for_branch(branch)
    if not existing.ok:
        _record_failure(reasons, f"gh_pr_list_failed: {existing.error}")
        return None, reasons
    if existing.value is not None:
        return existing.value, reasons
    # CCE-89 D1: enriched PR body. _compose_pr_body falls back to the
    # legacy "docs-agent run" sentinel when no enrichment data is passed,
    # preserving the pre-D1 shape for callers/tests that haven't been
    # updated.
    changed_files = _changed_files_in_head_commit(repo_root)
    body = _compose_pr_body(
        changed_files=changed_files,
        lens_paths=lens_paths,
        partial=partial,
        partial_reasons=partial_reasons,
        baseline_sha=baseline_sha,
        current_sha=current_sha,
        fact_warnings=fact_warnings,
    )
    created = gh.pr_create(branch, commit_msg, body)
    if not created.ok:
        _record_failure(reasons, f"gh_pr_create_failed: {created.error}")
        return None, reasons
    # CCE-89 D2: now that we have a fresh PR number, close prior open
    # docs-agent/* PRs unless human-edited. ALL reasons returned are
    # info_only=True; auto-close is hygiene, not a partial-flipping signal.
    close_reasons = _auto_close_superseded_docs_agent_prs(
        gh,
        new_pr_number=created.value,
        new_pr_branch=branch,
    )
    reasons.extend(close_reasons)
    return created.value, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    parser.add_argument("--no-pr", action="store_true")
    parser.add_argument(
        "--bootstrap-core",
        action="store_true",
        help="C2: author missing canonical-core pages from the manifest, then exit.",
    )
    parser.add_argument(
        "--today", default=None, help="ISO date for last_reviewed (bootstrap-core)."
    )
    parser.add_argument(
        "--time-budget-seconds",
        type=int,
        default=None,
        help="CCE-109 soft per-run budget (seconds). 0 = unlimited. "
        "Overrides config run.time_budget_seconds.",
    )
    args = parser.parse_args()
    if args.bootstrap_core:
        return run_bootstrap_core(
            args.repo_root, dry_run_dir=args.dry_run_subagents, today=args.today
        )
    return run(
        args.repo_root,
        dry_run_dir=args.dry_run_subagents,
        no_pr=args.no_pr,
        time_budget_seconds=args.time_budget_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
