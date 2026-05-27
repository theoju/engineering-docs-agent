from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "templates" / "workflow-pages.yml"


def test_template_exists():
    assert TPL.exists(), "templates/workflow-pages.yml must exist"


def test_required_permissions_and_actions():
    text = TPL.read_text()
    data = yaml.safe_load(text)
    perms = data["permissions"]
    assert perms.get("pages") == "write"
    assert perms.get("id-token") == "write"
    for pin in (
        "actions/checkout@v5",
        "actions/configure-pages@v6",
        "actions/setup-python@v6",
        "actions/upload-pages-artifact@v5",
        "actions/deploy-pages@v5",
    ):
        assert pin in text, f"missing pinned action {pin}"


def test_enablement_and_nojekyll_and_no_jekyll_build():
    text = TPL.read_text()
    assert "enablement: true" in text
    assert ".nojekyll" in text
    # The only acceptable "jekyll" is the .nojekyll marker; no legacy Jekyll.
    assert text.lower().replace(".nojekyll", "").find("jekyll") == -1


def test_default_build_workflow_filename_is_the_scaffold_target():
    # The setup skill writes this file as docs-agent-pages.yml and sets
    # publishing.build_workflow to that name; keep the contract visible.
    assert "docs-agent-pages.yml" in TPL.read_text()
