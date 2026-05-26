"""Detect the canonical-core page set and write .doc-core-manifest.json (C2).

Detection is stdlib-only and deterministic. The artifact is a sibling to
.doc-source-map.json under docs_dir; it declares each core page and the
source_files globs M uses for file-drift. Never raises on bad input.

`site_config` is the `site:` block itself (the {docs_dir, sections, ...} dict),
matching what setup_scaffold loads from the site YAML.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discover  # noqa: E402
import source_map  # noqa: E402,F401  used in write_core_manifest (Task 5)

_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")
_SLUG_NONWORD = re.compile(r"[^a-z0-9]+")
_BACKTICK = re.compile(r"`([^`\n]+)`")


def _agent_authored_section(site_config) -> dict | None:
    """The site section whose generator is agent-authored, or None. Never raises."""
    if not isinstance(site_config, dict):
        return None
    for s in site_config.get("sections") or []:
        if isinstance(s, dict) and s.get("generator") == "agent-authored":
            return s
    return None


def _source_root_glob(repo_root: Path) -> str | None:
    """A recursive *.py glob rooted at the detected Python scan dir, or None."""
    py = setup_discover.detect_python(Path(repo_root))
    if py.get("detected") and py.get("scan_dir"):
        return f"{py['scan_dir']}/**/*.py"
    return None


def _resolve_specs_dir(repo_root: Path, site_config, specs_dir=None) -> Path | None:
    """Resolve the specs directory: explicit arg wins; else the archive
    section's spec-like source; else docs/superpowers/specs. None if none exist.
    """
    repo_root = Path(repo_root)
    if specs_dir is not None:
        p = Path(specs_dir)
        p = p if p.is_absolute() else repo_root / p
        return p if p.is_dir() else None
    sections = site_config.get("sections") if isinstance(site_config, dict) else None
    for s in sections or []:
        if isinstance(s, dict) and s.get("generator") == "archive-index":
            for src in s.get("sources") or []:
                if isinstance(src, str) and "spec" in src.lower():
                    cand = repo_root / src
                    if cand.is_dir():
                        return cand
    default = repo_root / "docs" / "superpowers" / "specs"
    return default if default.is_dir() else None


def _spec_key(stem: str) -> str:
    """Derive a slug key from a spec filename stem: strip a leading YYYY-MM-DD-
    and any trailing -design and/or -plan suffixes (checked in turn), then
    slugify. Never empty for a non-empty stem.
    """
    s = _DATE_PREFIX.sub("", stem)
    for suf in ("-design", "-plan"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    slug = _SLUG_NONWORD.sub("-", s.lower()).strip("-")
    return slug or _SLUG_NONWORD.sub("-", stem.lower()).strip("-")


def _title_from_key(key: str) -> str:
    words = key.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) if words else key


def _extract_source_globs(text: str) -> list[str]:
    """Backtick-wrapped tokens that look like source paths: contain '/', no
    whitespace, and either carry a glob '*' or end in a code extension. A
    trailing ':line' citation suffix is stripped. Sorted + deduped. Never raises.
    """
    out: set[str] = set()
    for m in _BACKTICK.finditer(text):
        tok = m.group(1).strip()
        if not tok or " " in tok or "\t" in tok or "/" not in tok:
            continue
        base = tok.split(":", 1)[0]
        if "*" in base or base.endswith(_CODE_EXTS):
            out.add(base)
    return sorted(out)


def detect_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict | None:
    """Return {"version": 1, "pages": [...]} of candidate core pages, or None
    when there is no agent-authored section or nothing to document. Pure
    detection — no tracked-file filtering (write_core_manifest does that).

    A spec page with no extractable source globs and no detectable source root
    is emitted with source_files == []; this is intentional. Per the spec,
    entries that document nothing are dropped at build time by
    write_core_manifest (zero tracked-file matches), not here — detection only
    produces candidates.
    """
    repo_root = Path(repo_root)
    section = _agent_authored_section(site_config)
    if section is None:
        return None
    section_path = section.get("path")
    section_path = section_path.strip("/") if isinstance(section_path, str) else ""
    if not section_path:
        return None

    root_glob = _source_root_glob(repo_root)
    specs = _resolve_specs_dir(repo_root, site_config, specs_dir)

    pages: list[dict] = []
    if specs is not None:
        for sp in sorted(p for p in specs.glob("*.md") if p.is_file()):
            key = _spec_key(sp.stem)
            try:
                globs = _extract_source_globs(
                    sp.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                globs = []
            if not globs and root_glob:
                globs = [root_glob]
            pages.append(
                {
                    "key": key,
                    "title": _title_from_key(key),
                    "page": f"{section_path}/{key}.md",
                    "source_files": globs,
                }
            )

    if not pages:
        if root_glob is None:
            return None  # code-only with no detectable source root -> nothing
        key = "system-overview"
        pages = [
            {
                "key": key,
                "title": _title_from_key(key),
                "page": f"{section_path}/{key}.md",
                "source_files": [root_glob],
            }
        ]

    pages = _dedupe_and_sort(pages, section_path)
    if not pages:
        return None
    return {"version": 1, "pages": pages}


def write_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict:
    """Detect the manifest, drop entries whose globs match zero tracked files,
    and write <docs_dir>/.doc-core-manifest.json. Returns a ledger
    {"written": [...], "pages": N, "dropped": [keys]}. Writes nothing when
    detection yields None, docs_dir is unusable, or every entry is dropped.
    """
    repo_root = Path(repo_root)
    ledger: dict = {"written": [], "pages": 0, "dropped": []}
    manifest = detect_core_manifest(repo_root, site_config, specs_dir=specs_dir)
    if manifest is None:
        return ledger
    docs_dir = site_config.get("docs_dir") if isinstance(site_config, dict) else None
    if not isinstance(docs_dir, str) or not docs_dir.strip("/"):
        return ledger

    tracked = source_map._resolve_tracked_files(repo_root)
    kept: list[dict] = []
    for p in manifest["pages"]:
        regexes = [source_map._glob_to_regex(g) for g in p["source_files"]]
        if regexes and any(r.fullmatch(f) for r in regexes for f in tracked):
            kept.append(p)
        else:
            ledger["dropped"].append(p["key"])
    if not kept:
        return ledger

    artifact = {"version": 1, "pages": kept}
    out_rel = f"{docs_dir.rstrip('/')}/.doc-core-manifest.json"
    out_path = repo_root / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    ledger["written"] = [out_rel]
    ledger["pages"] = len(kept)
    return ledger


def _dedupe_and_sort(pages: list[dict], section_path: str) -> list[dict]:
    """Sort pages by key; disambiguate a colliding key deterministically by
    appending -2, -3, ... (in sorted order) and rewriting its page path to match.
    """
    out: list[dict] = []
    seen: dict[str, int] = {}
    for p in sorted(pages, key=lambda x: x["key"]):
        k = p["key"]
        if k in seen:
            seen[k] += 1
            nk = f"{k}-{seen[k]}"
            while nk in seen:  # avoid colliding with a literal key like api-2
                seen[k] += 1
                nk = f"{k}-{seen[k]}"
            seen[nk] = 1
            out.append({**p, "key": nk, "page": f"{section_path}/{nk}.md"})
        else:
            seen[k] = 1
            out.append(p)
    return out
