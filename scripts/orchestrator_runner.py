"""Orchestrator runner. Used by GitHub Actions and integration tests.

Calls subagents via the Claude Code CLI in production. In `--dry-run-subagents`
mode (used in tests), reads canned JSON outputs from a fixture directory
instead of invoking Claude.
"""

from __future__ import annotations
import argparse, fnmatch, json, os, re, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
import yaml

from gh_client import GhClient
from state_io import (
    ConfigError,
    StateError,
    add_partial,
    cleanup_empty_parents,
    load_config_validated,
    load_state_validated,
    load_voice_samples,
    resolve_lens,
    save_current_run,
    save_persistent_state,
)


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
    return m.group(1)


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
        fixture = dry_run_dir / f"fake_{name.replace('-', '_')}.json"
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
    try:
        return json.loads(canonical_text)
    except json.JSONDecodeError:
        # CCE-15: strict parse failed. Try prose-tolerant rescue. If we
        # extract a valid object, surface the rescue event via
        # out_reasons so dispatch_validated can roll it into the
        # pipeline's partial_reasons summary.
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
) -> tuple[dict | None, list[str]]:
    """Compose dispatch_subagent with validate_and_parse.

    Returns:
      Schema-valid clean:           (raw_dict, [])
      Schema-valid + rescued (CCE-15):
                                    (raw_dict, ["prose_contamination_rescued: <name>"])
      Schema-invalid:               (None, [...reasons including any rescue tag])
      Dispatch-None:                (None, []) — caller adds its own generic reason
      Schema-missing:               (None, ["schema_missing: <name>"])
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
    from contracts import validate_and_parse

    validated, reasons = validate_and_parse(name, raw)
    if validated is None:
        return None, dispatch_reasons + reasons
    # Return raw (not the dataclass) so call sites can keep using dict.get() patterns.
    return raw, dispatch_reasons


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
            print(f"bootstrap.progress.json write failed: {e}", file=sys.stderr)
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
            print(f"bootstrap.progress.json cleanup failed: {e}", file=sys.stderr)


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
    changed = sorted(
        {
            (f["path"] if isinstance(f, dict) else f)
            for pr in prs
            for f in (pr.get("files") or [])
            if isinstance(f, (dict, str))
            and (f.get("path") if isinstance(f, dict) else f)
        }
    )
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
    changed = {
        (f["path"] if isinstance(f, dict) else f)
        for pr in prs
        for f in (pr.get("files") or [])
        if isinstance(f, (dict, str)) and (f.get("path") if isinstance(f, dict) else f)
    }
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


def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int:
    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    state_path = repo_root / ".engineering-docs-agent" / "state.json"
    if not cfg_path.exists():
        print("no config", file=sys.stderr)
        return 2

    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2
    voice_samples = load_voice_samples(repo_root, config)
    try:
        state = load_state_validated(state_path)
    except StateError as e:
        print(f"state invalid: {e}", file=sys.stderr)
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
            return 0

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
        for r in reasons:
            add_partial(state, r)
        if sources is None:
            if not reasons:
                add_partial(state, "source_collector_invalid: returned None")
            sources = {"prs": [], "jira_issues": []}
        else:
            if sources.get("error"):
                add_partial(state, f"source_collector_error: {sources['error']}")
            if sources.get("partial"):
                add_partial(state, "source_collector_partial: true")

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
            add_partial(state, r)

        prs = sources.get("prs", [])
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
        for pr in prs:
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
            for r in reasons:
                add_partial(state, r)
            if summary is None:
                if not reasons:
                    add_partial(state, f"pr_summarizer_invalid: pr={pr['number']}")
                continue
            if summary.get("error"):
                add_partial(
                    state,
                    f"pr_summarizer_error: pr={pr['number']}: {summary['error']}",
                )
                continue
            # Use the PR's actual number, not summary's echo (which is fixture-static in tests).
            summary_with_pr = {**summary, "pr_number": pr["number"]}
            summaries.append(summary_with_pr)

        # Page authoring: batch doc_targets per (lens, page_hint).
        import frontmatter_contract as fmc

        editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
        per_target: dict[tuple[str, str], list[dict]] = {}
        for s in summaries:
            for t in s.get("doc_targets", []):
                per_target.setdefault((t["lens"], t["page_hint"]), []).append(s)

        authored: list[str] = []
        for (lens, hint), batch_summaries in per_target.items():
            try:
                lens_path, _opts = resolve_lens(config, lens)
            except KeyError:
                add_partial(state, f"unknown_lens: {lens}")
                continue
            target_path = repo_root / lens_path / hint
            try:
                rel = target_path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                add_partial(state, f"unsafe_page_path: {hint}")
                continue
            if not _page_target_is_editable(str(rel), editable_globs):
                add_partial(state, f"unsafe_page_path: {rel}")
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = "edit" if target_path.exists() else "create"
            out, reasons = dispatch_validated(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": action,
                    "lens": lens,
                    "summaries": batch_summaries,
                    "voice_samples": voice_samples,
                    "frontmatter_template": fmc.default_frontmatter_dict(
                        [
                            pr.get("url")
                            for s in batch_summaries
                            for pr in prs
                            if pr.get("number") == s.get("pr_number")
                        ]
                    ),
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            for r in reasons:
                add_partial(state, r)
            if out is None:
                if not reasons:
                    add_partial(state, f"page_author_invalid: {rel}")
                continue
            if out.get("ok"):
                authored.append(str(target_path))
                if dry_run_dir and not target_path.exists():
                    target_path.write_text(
                        fmc.default_frontmatter_text()
                        + f"# {hint}\n\nGenerated by docs-agent.\n"
                    )

        # Content validation
        if authored:
            validation, reasons = dispatch_validated(
                "content-validator",
                {
                    "paths": authored,
                    "config_path": str(cfg_path),
                    "voice_samples": voice_samples,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            for r in reasons:
                add_partial(state, r)
            if validation is None:
                if not reasons:
                    add_partial(state, "content_validator_invalid: returned None")
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
                        state["current_run"]["partial"] = True
                        state["current_run"]["partial_reasons"].append(
                            f"lint_block_unsafe_path: {fail['path']} (outside repo)"
                        )
                        continue
                    # Reject empty / "." paths that would cause git checkout HEAD -- .
                    # to restore the entire working tree.
                    if str(rel) in (".", ""):
                        state["current_run"]["partial"] = True
                        state["current_run"]["partial_reasons"].append(
                            f"lint_block_unsafe_path: empty path"
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
                    state["current_run"]["partial"] = True
                    state["current_run"]["partial_reasons"].append(
                        f"lint_block: {fail['path']} {fail['rule']}: {fail['message']}"
                    )

        # Archive index regeneration
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
        for pr in prs:
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
            )
            for r in reasons:
                add_partial(state, r)
            if verdict is None:
                if not reasons:
                    add_partial(state, f"gap_detector_invalid: pr_id={pr_id}")
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

        # CCE-40: promote current_run.head_sha into last_successful_run.
        # The merge of the docs-agent PR is what actually promotes this to
        # main; until then the advance lives only on the docs-agent branch
        # and on disk locally. If PR open fails, nothing reaches main and
        # the next run reads the unchanged committed state.
        state["last_successful_run"] = {
            "head_sha": state["current_run"]["head_sha"],
            "completed_at": now,
        }
        state["current_run"]["pr_number"] = None
        save_persistent_state(state_path, state)
        save_current_run(state_path, state)
        if no_pr:
            return 0
        branch = branch_name(now)
        gh = GhClient(repo_root)
        pr_number, pr_reasons = open_or_append_pr(
            repo_root,
            gh,
            branch=branch,
            now_iso=now,
            partial=state["current_run"]["partial"],
            partial_reasons=state["current_run"]["partial_reasons"],
        )
        for reason, info_only in pr_reasons:
            add_partial(state, reason, info_only=info_only)
        if pr_number is None:
            save_persistent_state(state_path, state)
            save_current_run(state_path, state)
            return 1
        state["current_run"]["pr_number"] = pr_number
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
        for r in reasons:
            add_partial(state, r)
        if notifier_result is None:
            if not reasons:
                add_partial(state, "notifier_invalid: returned None")
            save_persistent_state(state_path, state)
            save_current_run(state_path, state)
        return 0
    finally:
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
        print("no config", file=sys.stderr)
        return 2
    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2

    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        print("no docs_dir; nothing to bootstrap", file=sys.stderr)
        return 0

    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        print("no core manifest; run setup first", file=sys.stderr)
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
        remote_head = remote.get("last_successful_run", {}).get("head_sha", "")
    except (json.JSONDecodeError, AttributeError):
        return False
    return remote_head == our_head_sha


def _format_partial_digest(partial_reasons: list[str]) -> str:
    """Single-source format for partial_reasons.

    Used by:
    - PR body composer in open_or_append_pr
    - GITHUB_STEP_SUMMARY writer in _write_step_summary

    Returns an empty string when partial_reasons is empty so callers
    can detect the no-reasons case without re-checking the list.
    """
    if not partial_reasons:
        return ""
    lines = ["WARNING — Partial run", ""]
    lines.extend(f"- {r}" for r in partial_reasons)
    return "\n".join(lines)


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
    digest = _format_partial_digest(reasons)
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


def open_or_append_pr(
    repo_root: Path,
    gh: GhClient,
    *,
    branch: str,
    now_iso: str,
    partial: bool,
    partial_reasons: list[str],
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
        reasons.append(
            (f"checkout_failed: {checkout.stderr.strip()[:_STDERR_TRUNCATE]}", False)
        )
        return None, reasons

    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "."], capture_output=True, text=True
    )
    if add.returncode != 0:
        reasons.append(
            (f"git_add_failed: {add.stderr.strip()[:_STDERR_TRUNCATE]}", False)
        )
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
            reasons.append(
                (
                    f"push_failed_unknown: rev-parse failed (rc={local_head.returncode}); "
                    f"push stderr: {stderr_summary}",
                    False,
                )
            )
            return None, reasons
        if remote_sha == local_sha:
            reasons.append(
                (
                    f"push_tracking_setup_failed: {stderr_summary}",
                    True,
                )
            )
        elif lsremote.returncode != 0:
            reasons.append(
                (
                    f"push_failed_unknown: ls-remote rc={lsremote.returncode}; "
                    f"push stderr: {stderr_summary}",
                    False,
                )
            )
            return None, reasons
        else:
            reasons.append(
                (
                    f"push_refs_failed: {stderr_summary}",
                    False,
                )
            )
            return None, reasons

    existing = gh.pr_list_for_branch(branch)
    if not existing.ok:
        reasons.append((f"gh_pr_list_failed: {existing.error}", False))
        return None, reasons
    if existing.value is not None:
        return existing.value, reasons
    if partial:
        digest = _format_partial_digest(partial_reasons)
        body = digest if digest else "docs-agent run"
    else:
        body = "docs-agent run"
    created = gh.pr_create(branch, commit_msg, body)
    if not created.ok:
        reasons.append((f"gh_pr_create_failed: {created.error}", False))
        return None, reasons
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
    args = parser.parse_args()
    if args.bootstrap_core:
        return run_bootstrap_core(
            args.repo_root, dry_run_dir=args.dry_run_subagents, today=args.today
        )
    return run(args.repo_root, dry_run_dir=args.dry_run_subagents, no_pr=args.no_pr)


if __name__ == "__main__":
    sys.exit(main())
