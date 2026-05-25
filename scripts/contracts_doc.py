"""Generate a JSON-Schema contracts reference page set (CCE-23 capability API).

Pure functions parse/render; `generate_contracts` is the only writer. Reads the
`json-schema` extractor's `sources` (dirs of *.json) from the site config and
emits one markdown page per schema under <docs_dir>/<api path>/contracts/, with
an index. Overwrites generated pages every run (auto-generated banner). Skips a
missing/empty source cleanly; never emits an empty page set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import ConfigError, load_config_validated  # noqa: E402


def _type_str(prop: dict) -> str:
    if "$ref" in prop:
        return str(prop["$ref"]).rsplit("/", 1)[-1]
    if "enum" in prop:
        return "enum"
    for key in ("oneOf", "anyOf"):
        if prop.get(key):
            return " | ".join(_type_str(s or {}) for s in prop[key])
    if prop.get("allOf"):
        return " & ".join(_type_str(s or {}) for s in prop["allOf"])
    t = prop.get("type")
    if t == "array":
        items = prop.get("items") or {}
        return f"array[{_type_str(items)}]" if items else "array"
    if isinstance(t, list):
        return " | ".join(str(x) for x in t)
    return str(t) if t else "—"


def render_contract_page(name: str, schema: dict) -> str:
    title = schema.get("title") or name
    lines = [
        f"# {title}",
        "",
        "_Auto-generated from JSON Schema; do not edit by hand — "
        "see `scripts/contracts_doc.py`._",
        "",
    ]
    desc = schema.get("description")
    if desc:
        lines += [str(desc), ""]
    props = schema.get("properties") or {}
    if not props:
        lines += ["_No properties documented._", ""]
        return "\n".join(lines)
    required = set(schema.get("required") or [])
    lines += ["| Property | Type | Required | Description |", "|---|---|---|---|"]
    for pname, pschema in props.items():
        pschema = pschema or {}
        ptype = _type_str(pschema).replace("|", "\\|")
        req = "yes" if pname in required else "no"
        pdesc = (
            str(pschema.get("description", "") or "")
            .replace("\n", " ")
            .replace("|", "\\|")
        )
        lines.append(f"| `{pname}` | {ptype} | {req} | {pdesc} |")
    lines.append("")
    return "\n".join(lines)


def render_index(names: list[str]) -> str:
    lines = ["# Contracts", "", "_Auto-generated; do not edit by hand._", ""]
    for n in sorted(names):
        lines.append(f"- [{n}]({n}.md)")
    lines.append("")
    return "\n".join(lines)
