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


def test_enablement_field_is_absent_and_nojekyll_marker_present():
    """Regression guard: enablement: true is misleading (no-op on first
    deploy because the workflow token lacks admin scope; no-op forever
    after Pages exists). Pages bootstrap is done by scripts/enable_pages.py
    from SKILL.md step 6c using the operator's admin gh auth. See CCE-82."""
    import re

    text = TPL.read_text()
    assert not re.search(
        r"^\s*enablement:\s*['\"]?true['\"]?\s*$",
        text,
        re.MULTILINE,
    ), (
        "templates/workflow-pages.yml must not carry `enablement: true` in "
        "any form (quoted, unquoted, leading whitespace) — see CCE-82."
    )
    assert ".nojekyll" in text
    # The only acceptable "jekyll" is the .nojekyll marker; no legacy Jekyll.
    assert text.lower().replace(".nojekyll", "").find("jekyll") == -1


def test_configure_pages_step_has_no_with_block():
    """Structural guard against re-adding any `with:` block to configure-pages@v6.

    Currently no host configuration requires one. If a future change adds
    one, this test forces the maintainer to update both the test and the
    SKILL/CLAUDE.md documentation that explains WHY the field shouldn't
    be there. See CCE-82."""
    data = yaml.safe_load(TPL.read_text())
    build_steps = data["jobs"]["build"]["steps"]
    cp_step = next(
        s
        for s in build_steps
        if s.get("uses", "").startswith("actions/configure-pages@")
    )
    assert "with" not in cp_step, (
        f"configure-pages step must not carry a `with:` block; "
        f"found: {cp_step.get('with')}. See CCE-82."
    )


def test_default_build_workflow_filename_is_the_scaffold_target():
    # The setup skill writes this file as docs-agent-pages.yml and sets
    # publishing.build_workflow to that name; keep the contract visible.
    assert "docs-agent-pages.yml" in TPL.read_text()
