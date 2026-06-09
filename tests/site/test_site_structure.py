from __future__ import annotations

import contextlib
import inspect
import io
import sys
import types
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import site_structure  # noqa: E402

SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "api",
            "path": "api/",
            "title": "API reference",
            "generator": "api-extract",
        },
    ],
}


def test_plan_scaffold_emits_index_and_section_dirs():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    # the home page
    assert "docs/site-src/index.md" in files
    # a directory section gets an index stub (nav now lives in mkdocs.yml)
    assert "docs/site-src/api/index.md" in files
    # no per-dir .pages, no root .pages, no root SUMMARY.md anymore (CCE-106)
    assert not any(p.endswith(".pages") for p in files)
    assert "docs/site-src/SUMMARY.md" not in files


def test_section_index_stub_has_title_and_draft_frontmatter():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    stub = files["docs/site-src/api/index.md"].content
    assert "title: API reference" in stub
    assert "status: draft" in stub
    assert "API reference: content will be added here" in stub
    assert "This section is scaffolded" not in stub


def test_page_section_has_no_directory():
    # whats-new style single-page section (path ends in .md) → no dir/.pages
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"}
        ],
    }
    paths = {f.path for f in site_structure.plan_scaffold(site)}
    assert "docs/site-src/whats-new.md" in paths
    assert "docs/site-src/whats-new.md/.pages" not in paths


def test_single_page_section_kind_is_section_index():
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"}
        ],
    }
    page = next(
        f for f in site_structure.plan_scaffold(site) if f.path.endswith("whats-new.md")
    )
    assert page.kind == "section-index"


def test_empty_sections_emits_nothing():
    # no sections -> no .pages, no stubs, no SUMMARY (nav lives in mkdocs.yml)
    files = site_structure.plan_scaffold({"docs_dir": "docs", "sections": []})
    assert files == []


def test_title_with_colon_produces_parseable_yaml():
    site = {
        "docs_dir": "docs/site-src",
        "sections": [{"key": "api", "path": "api/", "title": "API: Reference Guide"}],
    }
    files = {f.path: f for f in site_structure.plan_scaffold(site)}
    # frontmatter of the section index must parse, with the title intact
    body = files["docs/site-src/api/index.md"].content
    front = body.split("---", 2)[1]
    assert yaml.safe_load(front)["title"] == "API: Reference Guide"


def test_mkdocs_yaml_generates_nav_from_sections():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=True, python_path_root="."
    )
    assert "nav:" in out
    # home -> page entry; api (directory section) -> directory cross-link
    assert "- Home: index.md" in out
    assert "- API reference: api/" in out


def test_nav_directory_cross_link_for_dirs_page_for_pages():
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "arch", "path": "architecture/", "title": "Architecture"},
            {"key": "whats-new", "path": "whats-new.md", "title": "What's New"},
        ],
    }
    out = site_structure.render_mkdocs_yaml(site, site_name="X", python_detected=False)
    assert "- Architecture: architecture/" in out  # dir -> trailing slash cross-link
    assert "- What's New: whats-new.md" in out  # page -> direct .md


def test_nav_title_with_colon_is_quoted():
    site = {
        "docs_dir": "docs/site-src",
        "sections": [{"key": "api", "path": "api/", "title": "API: Guide"}],
    }
    out = site_structure.render_mkdocs_yaml(site, site_name="X", python_detected=False)
    # the nav: block must parse as valid YAML with the title intact. Anchor on the
    # top-level "\nnav:" so the indented "  - literate-nav:" plugin key (which
    # contains the substring "nav:") cannot be mistaken for the nav block.
    nav = yaml.safe_load(out.split("\nnav:", 1)[1])
    assert nav == [{"API: Guide": "api/"}]


def test_plan_scaffold_emits_no_pages_and_no_root_summary():
    files = {f.path for f in site_structure.plan_scaffold(SITE)}
    assert not any(p.endswith(".pages") for p in files)
    assert "docs/site-src/SUMMARY.md" not in files
    # still emits the home + section index landings
    assert "docs/site-src/index.md" in files
    assert "docs/site-src/api/index.md" in files


_GROUPS = [
    {"name": "Generators", "modules": ["archive_indexes", "contracts_doc"]},
    {"name": "Lint", "modules": ["lint/*"]},
]


def test_assign_group_first_match_wins():
    assert site_structure.assign_group("archive_indexes", _GROUPS) == "Generators"


def test_assign_group_glob_matches_path_form():
    # a "lint/*" glob must match the dotted ident "lint.lint_runner"
    assert site_structure.assign_group("lint.lint_runner", _GROUPS) == "Lint"


def test_assign_group_unmatched_is_other():
    assert site_structure.assign_group("gh_client", _GROUPS) == "Other"


def test_assign_group_empty_groups_is_flat_sentinel():
    # no groups -> "" so the caller keeps the flat nav
    assert site_structure.assign_group("anything", []) == ""


def _exec_gen_ref(rendered: str, repo: Path, monkeypatch) -> dict:
    """Exec a rendered gen_ref_pages.py against a fake mkdocs_gen_files and
    return the captured Nav (a dict of nav_key -> doc path)."""
    fake = types.ModuleType("mkdocs_gen_files")

    class _Nav(dict):
        def build_literate_nav(self):
            return []

    @contextlib.contextmanager
    def _open(path, mode="r"):
        yield io.StringIO()

    fake.Nav = _Nav
    fake.open = _open
    fake.set_edit_path = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mkdocs_gen_files", fake)
    monkeypatch.chdir(repo)
    g = {"__name__": "gen_ref_pages"}
    exec(compile(rendered, "gen_ref_pages.py", "exec"), g)
    return dict(g["nav"])


def _seed_modules(repo: Path):
    pkg = repo / "scripts"
    (pkg / "lint").mkdir(parents=True)
    for name in ("archive_indexes.py", "contracts_doc.py", "gh_client.py"):
        (pkg / name).write_text("")
    (pkg / "lint" / "lint_runner.py").write_text("")
    (pkg / "_private.py").write_text("")  # underscore-prefixed: excluded


def test_rendered_gen_ref_groups_nav(tmp_path: Path, monkeypatch):
    _seed_modules(tmp_path)
    rendered = site_structure._GEN_REF_TEMPLATE.format(
        scan_dir="scripts",
        path_root="scripts",
        out_root="api",
        groups_literal=repr(_GROUPS),
        assign_group_src=inspect.getsource(site_structure.assign_group),
    )
    nav = _exec_gen_ref(rendered, tmp_path, monkeypatch)
    assert ("Generators", "archive_indexes") in nav
    assert ("Generators", "contracts_doc") in nav
    assert ("Lint", "lint", "lint_runner") in nav
    assert ("Other", "gh_client") in nav
    assert not any("_private" in "".join(k) for k in nav)  # excluded


def test_render_mkdocs_yaml_includes_repo_url_when_given():
    out = site_structure.render_mkdocs_yaml(
        SITE,
        site_name="X",
        python_detected=False,
        repo_url="https://github.com/o/n",
        edit_uri="edit/main/docs/site-src/",
    )
    assert "repo_url: https://github.com/o/n" in out
    assert "edit_uri: edit/main/docs/site-src/" in out


def test_render_mkdocs_yaml_omits_repo_url_when_absent():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "repo_url:" not in out
    assert "edit_uri:" not in out


def test_render_home_has_author_zone_and_empty_markers():
    out = site_structure.render_home(SITE)
    assert "docs-agent:overview:start" in out
    assert "docs-agent:overview:end" in out
    start = out.index("docs-agent:overview:start")
    end = out.index("docs-agent:overview:end")
    assert "grid cards" not in out[start:end]  # cards come from the generator


def test_rendered_gen_ref_flat_when_no_groups(tmp_path: Path, monkeypatch):
    _seed_modules(tmp_path)
    rendered = site_structure._GEN_REF_TEMPLATE.format(
        scan_dir="scripts",
        path_root="scripts",
        out_root="api",
        groups_literal=repr([]),
        assign_group_src=inspect.getsource(site_structure.assign_group),
    )
    nav = _exec_gen_ref(rendered, tmp_path, monkeypatch)
    assert ("archive_indexes",) in nav  # flat key, no group prefix
    assert ("lint", "lint_runner") in nav


def test_mkdocs_yaml_drops_awesome_pages():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "awesome-pages" not in out


def test_mkdocs_yaml_has_literate_nav_even_without_python():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "literate-nav" in out
    assert "nav_file: SUMMARY.md" in out


def test_mkdocs_yaml_python_still_has_gen_files_and_mkdocstrings():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=True, python_path_root="."
    )
    assert "gen-files" in out and "mkdocstrings" in out
    assert out.count("literate-nav") == 1  # not duplicated
