# Host config templates

Per-host starting configurations for `engineering-docs-agent`. Each file is a copy-pasteable `.engineering-docs-agent/config.yml` tuned to a specific known host. The corresponding runbook at `docs/host-onboarding/<host>.md` documents which fields the user must review before committing.

Templates here are validated by `tests/setup/test_host_onboarding_fixtures.py` via the production `load_config_validated` contract — anything that lands here passes the same checks the orchestrator runs at startup.
