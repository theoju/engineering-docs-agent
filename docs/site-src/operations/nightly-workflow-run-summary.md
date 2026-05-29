---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/71
synthesized_into: []
---

# Nightly Workflow Run Summary

The nightly workflow writes a run summary to `$GITHUB_STEP_SUMMARY` after every execution. This gives you a fast read on what the last nightly did — state snapshot, partial status, any errors — without downloading the forensics artifact.

## Where to find it

Open the GitHub Actions run for `.github/workflows/docs-agent-nightly.yml`, then click the **Run summary** step. The step writes the contents of `.engineering-docs-agent/state.json` directly into the workflow summary panel.

## How the run-summary step works

The step uses an explicit file-existence guard before reading the state file:

```bash
if [ -f .engineering-docs-agent/state.json ]; then
  jq -e '.' .engineering-docs-agent/state.json
else
  echo "(no state)"
fi
```

The `if [ -f ... ]` check is the key safety property. Earlier versions used a `cat ... 2>/dev/null | sed ...` pipeline, which swallowed `cat`'s non-zero exit code — the shell treats a pipe's exit status as the last command's exit, so the `|| echo "(no state)"` fallback never triggered correctly when the file was present but unreadable or malformed.

The `jq -e '.'` one-liner does two things: it pretty-prints the JSON and exits non-zero when the JSON is invalid. If the state file exists but contains invalid JSON, the step fails visibly rather than silently outputting garbage.

## Triaging a partial or failed nightly run

When the nightly completes with `partial: true` in the state, the run summary shows the state snapshot directly. Check `partial_reasons` in the JSON — each entry names the stage that failed and its error code.

You do not need the forensics artifact for most triage. The summary panel has the full state snapshot. Download the artifact only when you need raw subagent output or intermediate stage files.

## Related files

- `.github/workflows/docs-agent-nightly.yml` — the workflow definition; the run-summary step is the final step in the main job.
- `.engineering-docs-agent/state.json` — committed state file read by the step.
- `scripts/state_io.py` — the Python layer that writes `state.json` during the orchestrator run.
