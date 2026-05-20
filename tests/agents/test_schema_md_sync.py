# tests/agents/test_schema_md_sync.py
"""Drift-prevention: agents/<name>.md '## Output schema (canonical)' block
must be JSON-equivalent to agents/schemas/<name>.schema.json."""

from __future__ import annotations
import json
import re
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
SCHEMA_BLOCK = re.compile(
    r"## Output schema \(canonical\)\s*\n+```json\s*\n(.+?)\n```", re.DOTALL
)


@pytest.mark.parametrize(
    "agent_name",
    [
        "source-collector",
        "pr-summarizer",
        "page-author",
        "content-validator",
        "gap-detector",
        "publish-verifier",
        "notifier",
    ],
)
def test_md_schema_block_matches_canonical_schema_file(agent_name: str):
    md_path = AGENTS_DIR / f"{agent_name}.md"
    schema_path = AGENTS_DIR / "schemas" / f"{agent_name.replace('-', '_')}.schema.json"
    assert md_path.exists(), f"missing {md_path}"
    assert schema_path.exists(), f"missing {schema_path}"

    md_text = md_path.read_text()
    schema_text = schema_path.read_text()

    match = SCHEMA_BLOCK.search(md_text)
    assert match, (
        f"{agent_name}.md is missing the '## Output schema (canonical)' block. "
        f"Add it between '## Inputs' and '## Procedure', containing the "
        f"contents of agents/schemas/{agent_name.replace('-', '_')}.schema.json "
        f"inside a ```json fenced block."
    )

    md_schema = json.loads(match.group(1))
    canonical = json.loads(schema_text)
    assert md_schema == canonical, (
        f"{agent_name}.md schema block has drifted from "
        f"agents/schemas/{agent_name.replace('-', '_')}.schema.json. "
        f"Either update the .md block or update the .json file — they must be "
        f"JSON-equivalent (compared after json.loads on both sides)."
    )
