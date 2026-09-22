"""CCE-181: lint.external_repos must fail loud on every ambiguous declaration.

An entry declares EXACTLY one of `url` or `private: true`. Absence of `url` is
deliberately NOT an implicit "private": a typo would then silently downgrade a
public link, and -- worse -- a dropped `private` flag would silently publish a
URL for a repo that must not be advertised. Both directions are loud.
"""

import pytest

from scripts.external_refs import ExternalRepoConfigError, resolve_config

PUB = "https://github.com/theoju/engineering-docs-agent"


def test_absent_block_is_an_empty_mapping():
    assert resolve_config({}) == {}
    assert resolve_config({"lint": {}}) == {}


def test_a_public_entry_normalizes_with_defaults():
    out = resolve_config({"lint": {"external_repos": {"eda": {"url": PUB}}}})
    assert out == {
        "eda": {
            "url": PUB,
            "private": False,
            "ref": "main",
            "blob_template": "{url}/blob/{ref}/{path}",
        }
    }


def test_a_private_entry_carries_no_url():
    out = resolve_config({"lint": {"external_repos": {"ship": {"private": True}}}})
    assert out["ship"]["private"] is True
    assert out["ship"]["url"] is None


def test_overrides_survive_normalization():
    out = resolve_config(
        {
            "lint": {
                "external_repos": {
                    "gl": {
                        "url": "https://gitlab.com/o/r",
                        "ref": "master",
                        "blob_template": "{url}/-/blob/{ref}/{path}",
                    }
                }
            }
        }
    )
    assert out["gl"]["ref"] == "master"
    assert out["gl"]["blob_template"] == "{url}/-/blob/{ref}/{path}"


def test_both_url_and_private_is_rejected():
    with pytest.raises(ExternalRepoConfigError, match="both"):
        resolve_config(
            {"lint": {"external_repos": {"eda": {"url": PUB, "private": True}}}}
        )


def test_neither_url_nor_private_is_rejected():
    with pytest.raises(ExternalRepoConfigError, match="neither"):
        resolve_config({"lint": {"external_repos": {"eda": {"ref": "main"}}}})


def test_a_multi_segment_prefix_is_rejected():
    """Follows citation_source_roots: a nested tail is suffix-matching in
    disguise, and suffix-matching admits confabulated paths."""
    with pytest.raises(ExternalRepoConfigError, match="single segment"):
        resolve_config({"lint": {"external_repos": {"org/repo": {"url": PUB}}}})


def test_a_prefix_colliding_with_a_real_directory_is_rejected():
    """Without this, a host declaring `docs` while genuinely having docs/ would
    have real local paths rewritten into foreign links."""
    with pytest.raises(ExternalRepoConfigError, match="collides"):
        resolve_config(
            {"lint": {"external_repos": {"docs": {"url": PUB}}}},
            host_dirs=frozenset({"docs", "scripts"}),
        )


def test_a_non_colliding_prefix_passes_the_same_guard():
    out = resolve_config(
        {"lint": {"external_repos": {"eda": {"url": PUB}}}},
        host_dirs=frozenset({"docs", "scripts"}),
    )
    assert "eda" in out
