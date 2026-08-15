---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/219
synthesized_into: []
doc_kind: architecture
---

# `.graphifyignore`: excluding tracked fixtures from the knowledge graph

`tests/fixtures/diagrams/render/mermaid.min.js` is a vendored, minified bundle
kept deliberately as a render fixture. Because it's a real render dependency,
it's git-tracked — which means `.gitignore` can't exclude it from the graphify
knowledge-graph extraction pipeline. AST extraction walked every minified
symbol in that one file and emitted 2,167 nodes: 35% of the entire graph, all
of it noise that crowded out real code in god-node and community analysis.

## Why a manual filter didn't stick

Someone filtered the file out by hand on 2026-08-10. It came back. The
globally-seeded `.git/hooks/post-commit` hook runs `graphify update` after
every commit, re-extracting from a clean detect. The hook is AST-only and
costs nothing, which is exactly why the regression went unnoticed — it knows
nothing about a one-off manual filter, and any fix applied to the graph itself
rather than to its inputs gets silently undone by the next commit.

The lesson generalizes past this one file: a build artifact that is *tracked*
defeats every git-status-based exclusion, and a silent, free, automatic
refresh process is exactly the kind of thing that quietly reverts manual
curation. Check for one before concluding a graph regression came from your
own last action.

## The fix: `.graphifyignore`

`.graphifyignore` at the repo root uses gitignore syntax. Per graphify's
loader, it can only ever exclude *more* than `.gitignore` does — a pattern in
this file can never re-include something git already ignores, so it's safe to
add without risk of accidentally pulling ignored files back into the corpus.

It currently excludes minified/vendored bundles by extension:

```text
*.min.js
*.min.css
```

Because the exclusion lives in a tracked file read fresh on every extraction
run, the post-commit hook's clean detect honors it every time — there's no
manual step to repeat and nothing for a future commit to undo.

## Verified effect

With `*.min.js` / `*.min.css` excluded, file detection drops from 819 to 818
tracked files, and the graph goes from 6,196 to 4,029 nodes: zero dangling
links, and all 425 semantic nodes preserved. The 2,167 minified-symbol nodes
are gone; nothing else moved.

If you're extending `.graphifyignore` for a similar fixture, confirm the same
way: check the node count before and after, and confirm the semantic node
count is unchanged. A pattern that's too broad will silently drop real
semantic content along with the noise, and — per the AST/semantic split —
that kind of loss won't show up as an error, only as a smaller graph.

## Related

See `docs/runbooks/graphify-extraction-findings.md` for the broader
investigation this fix came out of, including why reference-aware batching
(a separate fix attempt, for low document-node yield rather than fixture
noise) was tried and rejected rather than merged.
