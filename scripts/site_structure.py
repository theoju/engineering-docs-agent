"""Turn a site: config block into a scaffold plan and apply it.

`plan_scaffold` and `render_mkdocs_yaml` are pure (no I/O) — keeping them
pure makes the structure trivially testable. `apply_scaffold` is the only
function that touches the filesystem; it writes missing files and never
clobbers existing (authored) content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScaffoldFile:
    path: str  # repo-relative POSIX path
    content: str
    # "home" | "section-index" | "pages" | "root-pages" | "mkdocs"
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
        "_This section is scaffolded. Content will be added here._\n"
    )


def _page_stub(section: dict) -> str:
    return f"---\ntitle: {_yaml_scalar(section['title'])}\nstatus: draft\n---\n\n# {section['title']}\n"


def render_home(site: dict) -> str:
    cards = []
    for s in site.get("sections", []):
        if s["key"] == "home":
            continue
        # Link to a resolvable .md target so mkdocs validates the link under
        # --strict; a bare "api/" is left as an unrecognized relative link.
        target = s["path"] if _is_page(s) else f"{s['path'].rstrip('/')}/index.md"
        cards.append(f"-   __{s['title']}__\n\n    [Open →]({target})")
    grid = '<div class="grid cards" markdown>\n\n' + "\n\n".join(cards) + "\n\n</div>"
    return (
        "---\ntitle: Home\nhide:\n  - toc\n---\n\n"
        "# Documentation\n\n"
        "Pick a section to get started.\n\n"
        f"{grid}\n"
    )


def plan_scaffold(site: dict) -> list[ScaffoldFile]:
    docs_dir = site["docs_dir"].rstrip("/")
    sections = site.get("sections", [])
    files: list[ScaffoldFile] = []

    # Root .pages: orders the top-level nav by section title, in config order.
    # Both title and path go through _yaml_scalar so any YAML-significant char
    # in a configured value cannot break the generated .pages.
    nav_lines = "\n".join(
        f"  - {_yaml_scalar(s['title'])}: {_yaml_scalar(s['path'].rstrip('/'))}"
        for s in sections
    )
    files.append(
        ScaffoldFile(f"{docs_dir}/.pages", f"nav:\n{nav_lines}\n", "root-pages")
    )

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
        # directory section: index stub + a .pages giving the section its title
        files.append(
            ScaffoldFile(
                f"{docs_dir}/{path}/index.md", _section_index_stub(s), "section-index"
            )
        )
        files.append(
            ScaffoldFile(
                f"{docs_dir}/{path}/.pages",
                f"title: {_yaml_scalar(s['title'])}\n",
                "pages",
            )
        )

    return files


_MKDOCS_TEMPLATE = """\
site_name: {site_name}
docs_dir: {docs_dir}
site_dir: site

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
  - awesome-pages
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


def _python_plugins_block(path_root: str) -> str:
    root = path_root or "."
    return (
        "  - gen-files:\n"
        "      scripts:\n"
        "        - gen_ref_pages.py\n"
        "  - literate-nav:\n"
        "      nav_file: SUMMARY.md\n"
        "  - mkdocstrings:\n"
        "      handlers:\n"
        "        python:\n"
        f'          paths: ["{root}"]\n'
        "          options:\n"
        "            show_source: false\n"
    )


def render_mkdocs_yaml(
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_path_root: str | None = None,
    openapi_enabled: bool = False,
) -> str:
    plugins = ""
    if python_detected:
        plugins += _python_plugins_block(python_path_root or ".")
    if openapi_enabled:
        plugins += _RENDER_SWAGGER_PLUGIN
    return _MKDOCS_TEMPLATE.format(
        site_name=_yaml_scalar(site_name),
        docs_dir=site["docs_dir"].rstrip("/"),
        theme=site.get("theme", "material"),
        mkdocstrings_plugin=plugins,
    )


def apply_scaffold(
    repo_root: Path, site: dict, *, site_name: str, python_detected: bool
) -> dict:
    """Write the scaffold under repo_root. Idempotent: existing files are
    left untouched (never clobber authored content); only missing files are
    created. Returns {"created": [...], "skipped": [...]}.
    """
    repo_root = Path(repo_root)
    created: list[str] = []
    skipped: list[str] = []

    planned = list(plan_scaffold(site))
    planned.append(
        ScaffoldFile(
            "mkdocs.yml",
            render_mkdocs_yaml(
                site, site_name=site_name, python_detected=python_detected
            ),
            "mkdocs",
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
