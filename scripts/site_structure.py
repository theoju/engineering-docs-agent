"""Turn a site: config block into a scaffold plan and apply it.

`plan_scaffold` and `render_mkdocs_yaml` are pure (no I/O) — keeping them
pure makes the structure trivially testable. `apply_scaffold` is the only
function that touches the filesystem; it writes missing files and never
clobbers existing (authored) content.
"""

from __future__ import annotations

import fnmatch
import inspect
import json
from dataclasses import dataclass
from pathlib import Path

import setup_discover
from managed_block import END as _OVERVIEW_END
from managed_block import START as _OVERVIEW_START


def assign_group(ident: str, groups: list) -> str:
    """Return the name of the first group whose module glob matches ``ident``,
    else "Other". An empty ``groups`` returns "" so the caller keeps the flat
    nav. Globs match against both the dotted ident ("a.b") and its path form
    ("a/b"), so a "lint/*" pattern matches a "lint.lint_runner" module.

    This function is embedded verbatim into the generated gen_ref_pages.py
    (see _GEN_REF_TEMPLATE) via inspect.getsource -- keep it self-contained:
    use only the stdlib ``fnmatch`` imported at the template's top, and no
    brace literals (so str.format on the template is safe).
    """
    if not groups:
        return ""
    path_form = ident.replace(".", "/")
    for group in groups:
        for pattern in group.get("modules", []):
            if fnmatch.fnmatchcase(ident, pattern) or fnmatch.fnmatchcase(
                path_form, pattern
            ):
                return group["name"]
    return "Other"


@dataclass(frozen=True)
class ScaffoldFile:
    path: str  # repo-relative POSIX path
    content: str
    # "home" | "section-index" | "mkdocs" | "gen-script" | "openapi-spec"
    kind: str


def _yaml_scalar(value: str) -> str:
    """Render a string as a YAML-safe scalar.

    Simple values pass through unquoted; anything containing YAML-significant
    characters is emitted as a JSON string (valid JSON is always valid YAML),
    which handles colons, quotes, leading indicators, etc.
    """
    risky = (
        ":" in value
        or "#" in value
        or "\n" in value
        or "\r" in value
        or value != value.strip()
        or (value and value[0] in "-?:,[]{}#&*!|>'\"%@`")
    )
    return json.dumps(value) if risky else value


def _is_page(section: dict) -> bool:
    """A section whose path ends in .md is a single page, not a directory."""
    return section.get("path", "").endswith(".md")


def _section_index_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {_yaml_scalar(section['title'])}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n\n"
        f"_{section['title']}: content will be added here as the docs-agent runner summarizes merged changes._\n"
    )


def _page_stub(section: dict) -> str:
    return f"---\ntitle: {_yaml_scalar(section['title'])}\nstatus: draft\n---\n\n# {section['title']}\n"


def render_home(site: dict) -> str:
    return (
        "---\ntitle: Home\nhide:\n  - toc\n---\n\n"
        "# Documentation\n\n"
        "Pick a section to get started.\n\n"
        f"{_OVERVIEW_START}\n{_OVERVIEW_END}\n"
    )


def plan_scaffold(site: dict) -> list[ScaffoldFile]:
    """Plan the on-disk landing stubs. The top-level nav is NOT scaffolded as
    a `.pages` (awesome-pages) or root `SUMMARY.md` anymore — it is generated
    directly into `mkdocs.yml` by ``render_mkdocs_yaml`` (CCE-106), where the
    `nav:` block's directory cross-links let literate-nav recurse into the
    gen-files reference subtree (which lives only in the build VFS). This
    function emits only the home page and per-section landing stubs.
    """
    docs_dir = site["docs_dir"].rstrip("/")
    sections = site.get("sections", [])
    files: list[ScaffoldFile] = []

    for s in sections:
        if s["key"] == "home":
            files.append(
                ScaffoldFile(
                    f"{docs_dir}/{s['path'].rstrip('/')}", render_home(site), "home"
                )
            )
            continue
        path = s["path"].rstrip("/")
        if _is_page(s):
            files.append(
                ScaffoldFile(f"{docs_dir}/{path}", _page_stub(s), "section-index")
            )
            continue
        # directory section: an index stub. Its title comes from the generated
        # mkdocs.yml nav entry, not a per-dir .pages.
        files.append(
            ScaffoldFile(
                f"{docs_dir}/{path}/index.md", _section_index_stub(s), "section-index"
            )
        )

    return files


_MKDOCS_TEMPLATE = """\
site_name: {site_name}
docs_dir: {docs_dir}
site_dir: site
{repo_block}
theme:
  name: {theme}
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.indexes
    - navigation.top
    - toc.follow
    - search.suggest
    - content.code.copy

plugins:
  - search
  - "literate-nav":
      nav_file: SUMMARY.md
{mkdocstrings_plugin}
markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
  - pymdownx.highlight
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.details
"""

_RENDER_SWAGGER_PLUGIN = "  - render_swagger\n"

_GEN_REF_TEMPLATE = '''\
"""Auto-generated by engineering-docs-agent setup. Runs at mkdocs build time
(mkdocs-gen-files) to emit one API page per module + a literate-nav SUMMARY,
grouped by service/component when GROUPS is non-empty (CCE-105)."""
import fnmatch
from pathlib import Path

import mkdocs_gen_files

SCAN_DIR = "{scan_dir}"
PATH_ROOT = "{path_root}"
OUT_ROOT = "{out_root}"
GROUPS = {groups_literal}


{assign_group_src}

nav = mkdocs_gen_files.Nav()
root = Path(PATH_ROOT)
for py in sorted(Path(SCAN_DIR).rglob("*.py")):
    if py.name.startswith("_") or any(p in ("tests", "test") for p in py.parts):
        continue
    try:
        ident_parts = py.relative_to(root).with_suffix("").parts
    except ValueError:
        continue  # a .py outside PATH_ROOT (when SCAN_DIR is broader); skip it
    if not ident_parts:
        continue
    doc = Path(*ident_parts).with_suffix(".md")
    ident = ".".join(ident_parts)
    group = assign_group(ident, GROUPS)
    nav_key = (group, *ident_parts) if group else ident_parts
    nav[nav_key] = doc.as_posix()
    with mkdocs_gen_files.open(Path(OUT_ROOT, "reference") / doc, "w") as fd:
        fd.write(f"# `{{ident}}`\\n\\n::: {{ident}}\\n")
    mkdocs_gen_files.set_edit_path(Path(OUT_ROOT, "reference") / doc, py)

with mkdocs_gen_files.open(Path(OUT_ROOT, "reference", "SUMMARY.md"), "w") as f:
    f.writelines(nav.build_literate_nav())
'''


def _openapi_stub(spec_filename: str) -> str:
    # !!swagger FILENAME!! resolves relative to this page's own directory;
    # apply_scaffold copies the spec file into that same directory.
    return f"---\ntitle: HTTP API\n---\n\n# HTTP API\n\n!!swagger {spec_filename}!!\n"


def _python_plugins_block(path_root: str) -> str:
    root = path_root or "."
    return (
        "  - gen-files:\n"
        "      scripts:\n"
        "        - gen_ref_pages.py\n"
        "  - mkdocstrings:\n"
        "      handlers:\n"
        "        python:\n"
        # json.dumps keeps the path a valid (always-quoted) YAML scalar even if
        # it contains a backslash or quote; valid JSON is valid YAML.
        f"          paths: [{json.dumps(root)}]\n"
        "          options:\n"
        "            show_source: false\n"
    )


def _render_nav(site: dict) -> str:
    """Render the top-level `nav:` block from the configured sections, in
    config order. A single-page section (path ends in .md) becomes a direct
    page entry; a directory section becomes a trailing-slash directory
    cross-link, which makes literate-nav recurse into that directory —
    including the gen-files reference subtree that exists only in the build
    VFS (a root SUMMARY.md markdown link cannot reach it). An empty sections
    list still emits a bare `nav:` (valid YAML).
    """
    lines = ["nav:"]
    for s in site.get("sections", []):
        target = s["path"] if _is_page(s) else s["path"].rstrip("/") + "/"
        lines.append(f"  - {_yaml_scalar(s['title'])}: {_yaml_scalar(target)}")
    return "\n".join(lines) + "\n"


def render_mkdocs_yaml(
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_path_root: str | None = None,
    openapi_enabled: bool = False,
    repo_url: str | None = None,
    edit_uri: str | None = None,
) -> str:
    plugins = ""
    if python_detected:
        plugins += _python_plugins_block(python_path_root or ".")
    if openapi_enabled:
        plugins += _RENDER_SWAGGER_PLUGIN
    repo_lines = ""
    if repo_url:
        # URLs and URI paths are safe YAML bare scalars; no quoting needed.
        repo_lines = f"repo_url: {repo_url}\n"
        if edit_uri:
            repo_lines += f"edit_uri: {edit_uri}\n"
    body = _MKDOCS_TEMPLATE.format(
        site_name=_yaml_scalar(site_name),
        docs_dir=site["docs_dir"].rstrip("/"),
        theme=site.get("theme", "material"),
        mkdocstrings_plugin=plugins,
        repo_block=repo_lines,
    )
    # Append the generated `nav:` block last. The literate-nav plugin key is
    # quoted ("literate-nav":) precisely so the only bare `nav:` substring in
    # the document is this block — making it the unambiguous nav source of
    # truth. literate-nav expands its directory cross-links at build time.
    return body + "\n" + _render_nav(site)


def apply_scaffold(
    repo_root: Path,
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_scan_dir: str | None = None,
    python_path_root: str | None = None,
    openapi_path: str | None = None,
) -> dict:
    """Write the scaffold under repo_root. Idempotent: existing files are
    left untouched (never clobber authored content); only missing files are
    created. Returns {"created": [...], "skipped": [...]}.
    """
    repo_root = Path(repo_root)
    created: list[str] = []
    skipped: list[str] = []

    origin = setup_discover.discover_git_origin(repo_root)
    repo_url = edit_uri = None
    if origin:
        repo_url = f"https://github.com/{origin['owner']}/{origin['repo']}"
        edit_uri = f"edit/main/{site['docs_dir'].rstrip('/')}/"

    planned = list(plan_scaffold(site))
    planned.append(
        ScaffoldFile(
            "mkdocs.yml",
            render_mkdocs_yaml(
                site,
                site_name=site_name,
                python_detected=python_detected,
                python_path_root=python_path_root,
                openapi_enabled=bool(openapi_path),
                repo_url=repo_url,
                edit_uri=edit_uri,
            ),
            "mkdocs",
        )
    )

    api_section = next(
        (s for s in site.get("sections", []) if s.get("generator") == "api-extract"),
        None,
    )
    api_path = api_section.get("path", "api").rstrip("/") if api_section else "api"
    api_groups = (api_section.get("groups") or []) if api_section else []

    if python_detected:
        planned.append(
            ScaffoldFile(
                "gen_ref_pages.py",
                _GEN_REF_TEMPLATE.format(
                    scan_dir=python_scan_dir or ".",
                    path_root=python_path_root or ".",
                    out_root=api_path,
                    groups_literal=repr(api_groups),
                    assign_group_src=inspect.getsource(assign_group),
                ),
                "gen-script",
            )
        )
    if openapi_path:
        docs_dir = site["docs_dir"].rstrip("/")
        spec_name = Path(openapi_path).name
        planned.append(
            ScaffoldFile(
                f"{docs_dir}/{api_path}/http.md",
                _openapi_stub(spec_name),
                "section-index",
            )
        )
        # Copy the committed spec (repo-root-relative) into the API docs dir so
        # the !!swagger <basename>!! token resolves under --strict. Skipped if
        # the source file is absent (the page still scaffolds).
        src_spec = repo_root / openapi_path
        if src_spec.is_file():
            planned.append(
                ScaffoldFile(
                    f"{docs_dir}/{api_path}/{spec_name}",
                    src_spec.read_text(encoding="utf-8"),
                    "openapi-spec",
                )
            )

    for f in planned:
        target = repo_root / f.path
        if target.exists():
            skipped.append(f.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        created.append(f.path)

    return {"created": created, "skipped": skipped}
