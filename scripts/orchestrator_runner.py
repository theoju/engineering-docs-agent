"""Orchestrator runner. Used by GitHub Actions and integration tests.

Calls subagents via the Claude Code CLI in production. In `--dry-run-subagents`
mode (used in tests), reads canned JSON outputs from a fixture directory
instead of invoking Claude.
"""

from __future__ import annotations
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
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
        "--allowedTools",
        " ".join(_AGENT_ALLOWED_TOOLS),
    ]
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
                    # add_partial writes into the already-initialised fresh current_run
                    add_partial(state, "stale_current_run_cleared")
            except ValueError:
                pass

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

    prs = sources.get("prs", [])
    jira_issues = sources.get("jira_issues", []) or []
    jira_lookup = {issue["key"]: issue for issue in jira_issues}

    summaries = []
    for pr in prs:
        jira_context = [
            jira_lookup[k] for k in pr.get("jira_keys", []) if k in jira_lookup
        ]
        summary, reasons = dispatch_validated(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": jira_context,
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
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
    import fnmatch

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
        if editable_globs and not any(
            fnmatch.fnmatch(str(rel), g) for g in editable_globs
        ):
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
                "frontmatter_template": {
                    "status": "draft",
                    "sources": [
                        pr.get("url")
                        for s in batch_summaries
                        for pr in prs
                        if pr.get("number") == s.get("pr_number")
                    ],
                    "synthesized_into": [],
                },
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
                    "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"
                    f"# {hint}\n\nGenerated by docs-agent.\n"
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

    for lens in config.get("docs", {}).get("lens_paths", {}):
        try:
            lens_path, opts = resolve_lens(config, lens)
        except KeyError:
            continue
        if opts.get("archive_index"):
            archive_indexes.regenerate(repo_root / lens_path)

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
        entry = "\n".join(entry_lines) + "\n\n"
        existing = whats_new.read_text() if whats_new.exists() else ""
        whats_new.write_text(entry + existing)

    state["current_run"]["pr_number"] = None
    state_path.write_text(json.dumps(state, indent=2))
    if no_pr:
        return 0
    branch = branch_name(now)
    gh = GhClient(repo_root)
    pr_number = open_or_append_pr(
        repo_root,
        gh,
        branch=branch,
        now_iso=now,
        partial=state["current_run"]["partial"],
        partial_reasons=state["current_run"]["partial_reasons"],
    )
    if pr_number is None:
        add_partial(state, "push_failed: see logs")
        state_path.write_text(json.dumps(state, indent=2))
        return 1
    state["current_run"]["pr_number"] = pr_number
    state_path.write_text(json.dumps(state, indent=2))

    # Compose digest and dispatch notifier.
    digest = {
        "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
        "run_summary_bullets": [
            f"PR #{s.get('pr_number')}: {s.get('what_changed', '')}" for s in summaries
        ],
        "gap_flags": [
            {"pr_id": v["pr_id"], "reasoning": v["reasoning"]}
            for v in gap_verdicts
            if v.get("needs_spec")
        ],
        "lint_failures": state["current_run"]["partial_reasons"],
        "partial_reasons": state["current_run"]["partial_reasons"],
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
        state_path.write_text(json.dumps(state, indent=2))
    return 0


def branch_name(now_iso: str) -> str:
    return f"docs-agent/{now_iso[:13]}"


def open_or_append_pr(
    repo_root: Path,
    gh: GhClient,
    *,
    branch: str,
    now_iso: str,
    partial: bool,
    partial_reasons: list[str],
) -> int | None:
    checkout = subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-B", branch],
        capture_output=True,
        text=True,
    )
    if checkout.returncode != 0:
        return None
    add = subprocess.run(
        ["git", "-C", str(repo_root), "add", "."], capture_output=True, text=True
    )
    if add.returncode != 0:
        return None
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
        return None
    existing = gh.pr_list_for_branch(branch)
    if not existing.ok:
        return None
    if existing.value is not None:
        return existing.value
    body = (
        "WARNING — Partial run — " + "; ".join(partial_reasons)
        if partial
        else "docs-agent run"
    )
    created = gh.pr_create(branch, commit_msg, body)
    if not created.ok:
        return None
    return created.value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    parser.add_argument("--no-pr", action="store_true")
    args = parser.parse_args()
    return run(args.repo_root, dry_run_dir=args.dry_run_subagents, no_pr=args.no_pr)


if __name__ == "__main__":
    sys.exit(main())
