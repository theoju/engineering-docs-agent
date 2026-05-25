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


def _find_contracts_section(site: dict) -> dict | None:
    for s in site.get("sections", []) or []:
        if s.get("generator") == "api-extract" and "json-schema" in (
            s.get("extractors") or []
        ):
            return s
    return None


def generate_contracts(repo_root: Path, site_config: dict) -> dict:
    """Render every *.json under the json-schema section's `sources` to a
    contracts page. Returns {"written": [...], "skipped": [...]} of repo-relative
    POSIX paths. Skips (records) missing/empty sources and malformed schemas;
    never emits an empty page set.
    """
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []

    section = _find_contracts_section(site_config)
    if section is None:
        return {"written": written, "skipped": skipped}
    sources = section.get("sources") or []
    if not sources:
        return {"written": written, "skipped": skipped}

    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")
    section_path = (section.get("path") or "").rstrip("/")
    out_dir = repo_root / docs_dir / section_path / "contracts"

    names: list[str] = []
    for source in sources:
        src_dir = repo_root / source
        if not src_dir.is_dir():
            print(f"warning: contracts source not found: {source}", file=sys.stderr)
            skipped.append(source)
            continue
        schema_files = sorted(src_dir.glob("*.json"))
        if not schema_files:
            print(f"warning: no *.json in contracts source: {source}", file=sys.stderr)
            skipped.append(source)
            continue
        for path in schema_files:
            rel = f"{docs_dir}/{section_path}/contracts/{path.stem}.md"
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(
                    f"warning: skipping malformed schema {path.name}: {exc}",
                    file=sys.stderr,
                )
                skipped.append(str(Path(source) / path.name))
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{path.stem}.md").write_text(
                render_contract_page(path.stem, schema), encoding="utf-8"
            )
            written.append(rel)
            names.append(path.stem)

    if names:
        (out_dir / "index.md").write_text(render_index(names), encoding="utf-8")
        written.append(f"{docs_dir}/{section_path}/contracts/index.md")

    return {"written": written, "skipped": skipped}
