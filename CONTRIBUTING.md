# Contributing to engineering-docs-agent

## Dogfood ↔ Template Parity

This plugin ships `templates/workflow-run.yml` (the generic workflow
installed by the setup skill into arbitrary host repos) AND dogfoods itself
via `.github/workflows/docs-agent-nightly.yml`. Both files are tested for
parity by `tests/templates/test_workflow_run_parity.py`.

Edits to `.github/workflows/docs-agent-nightly.yml` require either:

1. A corresponding update to `templates/workflow-run.yml` (the preferred
   path for any change that should ship to host repos), or
2. An explicit entry added to `_ALLOWLIST` in
   `tests/templates/test_workflow_run_parity.py` with rationale (use this
   only when the divergence is intentionally host-specific or
   template-specific).

The parity test runs in CI. A failing test prints the divergence + the
allowlist key needed to suppress it. Suppressing without rationale is a
review-time block.

## Release tagging

Plugin releases are tagged so `templates/workflow-run.yml` can pin
`actions/checkout@v5 ref: vX.Y.Z` for the plugin-vendoring step. Cut a
release tag immediately after merging any PR that changes the plugin's
public surface (templates, setup skill, runner contracts):

    gh release create vX.Y.Z \
        --target main \
        --title "vX.Y.Z — short description" \
        --notes "Summary of changes."
    gh release view vX.Y.Z

Cut the tag within 5 minutes of merge — hosts re-scaffolding before the
tag exists will fail at the plugin-vendoring checkout step.
