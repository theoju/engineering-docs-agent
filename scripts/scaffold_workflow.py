"""Render templates/workflow-run.yml for a host repo.

Rewrites the cron line to a deterministic per-host minute so 100 hosts
don't all hit :07 UTC. Everything else is byte-for-byte copy.

Usage::

    python scripts/scaffold_workflow.py --owner OWNER --repo REPO \\
        [--template PATH] [--out PATH]

`--template` defaults to the plugin's templates/workflow-run.yml; `-` reads stdin.
`--out` defaults to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# CI1 fix: group 2 captures the whitespace AFTER the second `7` so the
# substitution `\g<1>{minute} 7\g<2>\g<3>` preserves the space (group 2 starts
# with `\s+`, NOT `*`). The pre-fix form ate the space and produced `42 7* * *`.
# Group 3 tolerates trailing whitespace or an inline comment.
_CRON_PATTERN = re.compile(r'^(\s+- cron: ")7 7(\s+\* \* \*")(.*)$', re.MULTILINE)


def deterministic_cron_minute(owner: str, repo: str) -> int:
    """Stable per-host cron minute in [5, 55].

    Same owner/repo → same minute (no diff churn on re-scaffold).
    SHA-256 mod 51 over distinct owner/repo strings is uniform across [0, 50];
    offset to [5, 55] to stay within GitHub off-minute guidance.
    """
    digest = hashlib.sha256(f"{owner}/{repo}".encode()).hexdigest()
    return int(digest, 16) % 51 + 5


def rewrite_cron(text: str, owner: str, repo: str) -> str:
    """Replace `cron: "7 7 * * *"` with the deterministic per-host minute.

    Anchored substitution. Raises if the template has zero or more than one
    matching line (structural drift guard).
    """
    minute = deterministic_cron_minute(owner, repo)
    new_text, n = _CRON_PATTERN.subn(rf"\g<1>{minute} 7\g<2>\g<3>", text)
    if n != 1:
        raise RuntimeError(
            f"Expected exactly 1 cron line matching the anchor; found {n}. "
            "Template structure changed — update scripts/scaffold_workflow.py "
            "or its tests."
        )
    return new_text


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--template",
        default=None,
        help='Template path; "-" for stdin; default plugin templates/workflow-run.yml',
    )
    parser.add_argument("--out", default=None, help="Output path; default stdout")
    args = parser.parse_args()

    if args.template == "-":
        text = sys.stdin.read()
    elif args.template:
        text = Path(args.template).read_text()
    else:
        plugin_root = Path(__file__).resolve().parent.parent
        text = (plugin_root / "templates" / "workflow-run.yml").read_text()

    rendered = rewrite_cron(text, args.owner, args.repo)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
