"""scripts/stderr_emit — single point for stderr writes from the docs-agent pipeline.

This is a LEAF module: it imports only stdlib (sys, re) and is depended on
by state_io.py and orchestrator_runner.py. It MUST NOT import from state_io
or orchestrator_runner — doing so creates a cycle that breaks state_io's
role as the data layer. If structured emit is wanted later, build a
separate module that wraps these helpers; do NOT retrofit state into
stderr_emit.

The flush=True invariant is locked via _OBSERVABILITY_FLUSH so a future
copy-paste cannot drop it.

CCE-74: centralizes the redacted stderr write that previously lived in
scripts/orchestrator_runner.py:1832-1846 (`_CREDENTIAL_URL_RE` +
`_redact_credentials`) and in scripts/orchestrator_runner.py:1849-1863
(`_record_failure`'s emit line). Caller migration happens in subsequent
implementation steps; this module is the prerequisite.
"""

from __future__ import annotations

import re
import sys

# _OBSERVABILITY_FLUSH is exported by name to orchestrator_runner's
# _emit_shutdown_dump (which needs direct print() with flush=True so
# OSError propagates — emit_stderr/emit_log swallow it). The underscore
# prefix communicates "implementation constant, not a config knob —
# do NOT mutate at call sites" but it IS intentionally a cross-module
# export. If a future module-level lint flags this, add the symbol to
# the lint's allowlist rather than renaming — the underscore semantics
# (constant, not API) are preferred.
_OBSERVABILITY_FLUSH = True

# Pattern and substitution kept identical to pre-CCE-74
# orchestrator_runner._CREDENTIAL_URL_RE (line 1832) so callers migrated
# in Task 5 (and the existing test_open_or_append_pr.py:779 assertion
# `"<redacted>" in err`) see no behavioral change. Matches both http://
# and https://; replaces any user[:pass] segment with `<redacted>`.
_CREDENTIAL_URL_RE = re.compile(r"(https?://)[^@/\s]*@")


def _redact_credentials(text: str) -> str:
    """Replace `https?://user[:token]@host` with `https?://<redacted>@host`.

    Idempotent. Returns the input verbatim if no credential pattern matches.
    Moved verbatim from scripts/orchestrator_runner.py:1832-1846 (CCE-73 origin).
    """
    return _CREDENTIAL_URL_RE.sub(r"\1<redacted>@", text)


def emit_stderr(reason: str, *, info_only: bool = False) -> None:
    """Emit a redacted reason to stderr with PARTIAL or INFO prefix.

    Called from state_io.add_partial on EVERY call (not just newly-appended)
    so retry-loop sequencing is visible — a flaky upstream calling back with
    the same reason 10x produces 10 stderr lines, surfacing the retry storm.
    State-side dedup at state_io.py still applies; stderr is the unbounded
    log stream.

    Side-effect-only. Best-effort: OSError on stderr is caught and discarded
    so a closed/broken stderr cannot crash the orchestrator. Callers that
    require OSError propagation (e.g., `_emit_shutdown_dump` at orchestrator
    shutdown) must NOT use this helper — they call `print(..., flush=True)`
    directly.
    """
    prefix = "INFO" if info_only else "PARTIAL"
    safe = _redact_credentials(reason)
    try:
        print(
            f"docs-agent {prefix}: {safe}",
            file=sys.stderr,
            flush=_OBSERVABILITY_FLUSH,
        )
    except OSError:
        # Diagnostic stream failure must never crash the orchestrator.
        pass


def emit_log(text: str) -> None:
    """Raw-text stderr emit with flush=True. No prefix, no redaction.

    For operator diagnostic lines that are not partial_reasons: bootstrap
    progress, exception messages from non-credential code paths, etc.
    Replaces existing `print(..., file=sys.stderr)` calls at
    scripts/orchestrator_runner.py lines 643, 683, 969, 975, 981, 1493,
    1498, 1503, 1508 — locks flush=True so a future contributor cannot
    drop it via copy-paste from older code.

    Best-effort: OSError swallowed (same rationale as emit_stderr).
    Callers that require redaction MUST call _redact_credentials themselves
    BEFORE passing the text in.
    """
    try:
        print(text, file=sys.stderr, flush=_OBSERVABILITY_FLUSH)
    except OSError:
        pass
