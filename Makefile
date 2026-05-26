# Docs build + diagram render gate. Local convenience; CI uses docs.yml.
DOCS_DIR ?= docs/site-src
SITE_DIR ?= site

.PHONY: docs-verify
docs-verify:
	@python3 -c "import playwright" 2>/dev/null || { \
	  echo "diagram gate unavailable: pip install -r requirements-docs.txt && playwright install chromium"; \
	  exit 0; }
	mkdocs build --strict
	python3 scripts/verify_diagrams.py --site-dir $(SITE_DIR) --source-dir $(DOCS_DIR) --json
