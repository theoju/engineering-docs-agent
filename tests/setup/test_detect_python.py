from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import setup_discover  # noqa: E402


def test_detects_top_level_package(tmp_path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("def f(): ...\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": True, "scan_dir": "mypkg", "path_root": "."}


def test_detects_loose_modules_in_scripts(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "thing.py").write_text("x = 1\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": True, "scan_dir": "scripts", "path_root": "scripts"}


def test_no_python_returns_undetected(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n")
    out = setup_discover.detect_python(tmp_path)
    assert out == {"detected": False, "scan_dir": None, "path_root": None}


def test_package_wins_over_loose_dir(tmp_path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    loose = tmp_path / "scripts"
    loose.mkdir()
    (loose / "z.py").write_text("y = 2\n")
    out = setup_discover.detect_python(tmp_path)
    assert out["scan_dir"] == "app" and out["path_root"] == "."


def test_discover_includes_python_and_openapi_hint(tmp_path):
    d = tmp_path / "scripts"
    d.mkdir()
    (d / "a.py").write_text("a = 1\n")
    (tmp_path / "openapi.json").write_text("{}")
    out = setup_discover.discover(tmp_path)
    assert out["python"]["detected"] is True
    assert out["openapi_hint"] == "openapi.json"


def test_openapi_hint_none_when_absent(tmp_path):
    assert setup_discover.detect_openapi_hint(tmp_path) is None


def test_openapi_hint_detects_yaml_variant(tmp_path):
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0\n")
    assert setup_discover.detect_openapi_hint(tmp_path) == "openapi.yaml"
