from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "internal_links.py"
FIX = Path(__file__).parent.parent / "fixtures" / "internal_links"


def _run(paths, cfg):
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_good(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "internal_links"
    assert out["severity"] == "block"
    assert all(r["ok"] for r in out["results"])


def test_broken(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_broken.md"], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "does-not-exist.md" in msg


def test_external_links_skipped(tmp_path):
    p = tmp_path / "ext.md"
    p.write_text("[ext](https://example.com)\n[mail](mailto:x@y.z)\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0


# ---------------------------------------------------------------------------
# Example links inside code are illustrations, not navigation.
#
# Incident (2026-08-21, theoju/claude-code-self-assessment runs 32460602658 and
# 32495019606): the page documenting `extractDocRefs` — a function whose entire
# purpose is parsing markdown links out of CLAUDE.md — was blocked twice on
# `broken internal link(s): docs/runbook.md` and then `docs/foo.md`. Both come
# verbatim from the source material the page was written from: the design spec
# writes the syntax as `[x](docs/foo.md)`, and the unit test fixture contains
# "Also [the runbook](docs/runbook.md).". The page cannot document a markdown-
# link parser without showing a markdown link, so the author was correct and
# this rule was wrong.
#
# The cost is not one blocked page. Post-CCE-140 the deferral skip abandons a
# repeatedly-blocked PR and the baseline moves past it, so the page is simply
# never written and nothing is red anywhere.
#
# `citation_exists` — the sibling rule in the same directory — has stripped
# fenced blocks since CCE-110 for exactly this reason ("fenced examples are
# legitimately hypothetical"). This rule never got it. The fix imports that
# helper rather than reimplementing it; it is a documented shared-helper
# contract.
# ---------------------------------------------------------------------------


def test_fenced_example_link_is_not_a_broken_link(tmp_path):
    """The live repro: a markdown link shown inside a fenced example."""
    p = tmp_path / "page.md"
    p.write_text(
        "# Linked-doc credit\n\n"
        "`extractDocRefs` reads three syntaxes:\n\n"
        "```markdown\n"
        "Also [the runbook](docs/runbook.md).\n"
        "```\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, f"fenced example must not block: {out['results'][0]['message']}"


def test_inline_code_span_example_link_is_not_a_broken_link(tmp_path):
    """The form the source spec actually uses: a link inside an inline span."""
    p = tmp_path / "page.md"
    p.write_text("Markdown links (`[x](docs/foo.md)`) are one of three syntaxes.\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, f"inline span must not block: {out['results'][0]['message']}"


def test_double_backtick_span_example_link_is_not_a_broken_link(tmp_path):
    """`` `[x](docs/foo.md)` `` — a span delimited by a RUN of backticks.

    This is how the spec writes it, because the example itself contains
    backticks. A single-backtick-only matcher misses the outer delimiters and
    the link leaks back out to the link matcher.
    """
    p = tmp_path / "page.md"
    p.write_text("Backticked paths (`` `[x](docs/foo.md)` ``) also count.\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, f"double-tick span must not block: {out['results'][0]['message']}"


def test_real_broken_link_beside_an_example_still_blocks(tmp_path):
    """Strictness guard. Stripping code must not become a blanket amnesty."""
    p = tmp_path / "page.md"
    p.write_text(
        "Example: `[x](docs/foo.md)`\n\n"
        "```markdown\n[y](docs/fenced-example.md)\n```\n\n"
        "But this one is a real link: [gone](docs/really-missing.md)\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 1, "a genuine broken link in prose must still block"
    msg = out["results"][0]["message"]
    assert "docs/really-missing.md" in msg
    assert "docs/foo.md" not in msg, f"example link leaked into the report: {msg}"
    assert "docs/fenced-example.md" not in msg, f"fenced link leaked: {msg}"


def test_broken_link_after_a_closed_fence_still_blocks(tmp_path):
    """Fence stripping must resume checking after the fence closes."""
    p = tmp_path / "page.md"
    p.write_text("```\n[a](docs/in-fence.md)\n```\n\n[b](docs/after-fence.md)\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "docs/after-fence.md" in msg
    assert "docs/in-fence.md" not in msg


def test_unterminated_fence_fails_closed(tmp_path):
    """CCE-131 parity: an unclosed fence must not disable the rest of the file.

    `citation_exists` hit exactly this — an unterminated fence swallowed every
    line to EOF and silently switched off a Tier-1 block rule. The imported
    helper already fails closed; this pins that the behaviour carries over here
    rather than being re-broken by a local reimplementation.
    """
    p = tmp_path / "page.md"
    p.write_text("```\nnever closed\n\n[b](docs/after-unclosed.md)\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 1, "an unterminated fence must not suppress later links"
    assert "docs/after-unclosed.md" in out["results"][0]["message"]


def test_working_relative_link_still_passes(tmp_path):
    """The rule's actual job, unaffected."""
    p = tmp_path / "page.md"
    (tmp_path / "target.md").touch()
    p.write_text("Example `[x](docs/foo.md)` and a real one: [t](./target.md)\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, out["results"][0]["message"]
