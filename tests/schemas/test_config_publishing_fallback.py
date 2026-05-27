import json
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "templates" / "config.schema.json").read_text())


def _publishing(extra):
    base = {
        "base_url": "https://x.github.io/r/",
        "build_workflow": "docs-agent-pages.yml",
        "url_map_rule": "directory",
    }
    base.update(extra)
    return base


def test_build_command_and_site_dir_are_accepted():
    pub = _publishing({"build_command": "npm run build", "site_dir": "build"})
    jsonschema.validate(pub, SCHEMA["properties"]["publishing"])


def test_publishing_still_requires_core_fields():
    with_missing = {"build_command": "x"}  # no base_url/build_workflow/url_map_rule
    try:
        jsonschema.validate(with_missing, SCHEMA["properties"]["publishing"])
        assert False, "expected ValidationError for missing required fields"
    except jsonschema.ValidationError:
        pass
