from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docs_requirements_lists_api_plugins():
    text = (_REPO_ROOT / "templates" / "docs-requirements.txt").read_text()
    for dep in (
        "mkdocstrings[python]",
        "mkdocs-gen-files",
        "mkdocs-literate-nav",
        "mkdocs-render-swagger-plugin",
    ):
        assert dep in text
