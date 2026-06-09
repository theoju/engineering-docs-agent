"""Clobber-safe managed-region upsert for generated docs blocks.

Pure (no I/O). A generator owns the delimited START..END region of a file;
author prose outside the markers survives every regeneration. This is the
single place the docs-agent's "never rewrite an authored index.md" rule is
reversed -- for the delimited block only (CCE-106).
"""

from __future__ import annotations

MARKER = "docs-agent:overview"
START = f"<!-- {MARKER}:start -->"
END = f"<!-- {MARKER}:end -->"


def upsert_managed_block(existing_text: str, block_body: str) -> str:
    """Return ``existing_text`` with the START..END region's body replaced by
    ``block_body``. If no region exists, append one at end-of-file (preceded by
    a blank line). Text outside the markers is preserved byte-for-byte.

    Raises ValueError on a malformed file (more than one START/END, an unbalanced
    pair, or END before START) so the caller can record an ``info_only`` partial
    rather than crash the run.
    """
    n_start = existing_text.count(START)
    n_end = existing_text.count(END)
    if n_start > 1 or n_end > 1:
        raise ValueError(
            f"managed block markers must appear at most once "
            f"(start={n_start}, end={n_end})"
        )
    if n_start != n_end:
        raise ValueError(
            f"unbalanced managed block markers (start={n_start}, end={n_end})"
        )

    block = f"{START}\n{block_body}\n{END}"

    if n_start == 0:
        if not existing_text.strip():
            return block + "\n"
        return existing_text.rstrip("\n") + "\n\n" + block + "\n"

    start_idx = existing_text.index(START)
    end_idx = existing_text.index(END)
    if end_idx < start_idx:
        raise ValueError("END marker precedes START marker")
    before = existing_text[:start_idx]
    after = existing_text[end_idx + len(END) :]
    return f"{before}{block}{after}"
