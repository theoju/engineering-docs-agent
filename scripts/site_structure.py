"""Pure helpers that turn a site: config block into a scaffold plan.

No filesystem I/O lives here — `plan_scaffold` returns the intended files
and `apply_scaffold` (added later) does the writing. Keeping the planning
pure makes the structure trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaffoldFile:
    path: str  # repo-relative POSIX path
    content: str
    kind: str  # "home" | "section-index" | "pages" | "root-pages"


def _is_page(section: dict) -> bool:
    """A section whose path ends in .md is a single page, not a directory."""
    return section.get("path", "").endswith(".md")


def _section_index_stub(section: dict) -> str:
    return (
        "---\n"
        f"title: {section['title']}\n"
        "status: draft\n"
        "---\n\n"
        f"# {section['title']}\n\n"
        "_This section is scaffolded. Content will be added here._\n"
    )


def _page_stub(section: dict) -> str:
    return (
        f"---\ntitle: {section['title']}\nstatus: draft\n---\n\n# {section['title']}\n"
    )


def plan_scaffold(site: dict) -> list[ScaffoldFile]:
    docs_dir = site["docs_dir"].rstrip("/")
    sections = site.get("sections", [])
    files: list[ScaffoldFile] = []

    # Root .pages: orders the top-level nav by section title, in config order.
    nav_lines = "\n".join(f"  - {s['title']}: {s['path']}" for s in sections)
    files.append(
        ScaffoldFile(f"{docs_dir}/.pages", f"nav:\n{nav_lines}\n", "root-pages")
    )

    for s in sections:
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
            ScaffoldFile(f"{docs_dir}/{path}/.pages", f"title: {s['title']}\n", "pages")
        )

    return files
