# fakes_mixed_block — the CCE-140/CCE-151 mixed window

Three PRs, three DIFFERENT doc targets, one of them blocked on lint.

This is the case `_dispatch`'s per-PR fixture override (`<stem>__pr<N>.json`,
`orchestrator_runner.py`) was built for and which, until CCE-151, nothing
actually used. Its docstring states the reason plainly: without per-PR
fixtures every PR reads the same summarizer file, so every page batch contains
every PR and a window can only land or fail *as a whole* — under that
constraint the CCE-140 rule ("advance only to the last PR whose pages all
landed") says nothing, because there is no partial ordering to test.

The override applies to **pr-summarizer**, not to page-author or
content-validator: those two dispatch without a `pr` key in their inputs
(page-author is dispatched per target-batch, content-validator once for all
authored paths), so `__pr<N>` fixtures for them are silently ignored. Route
per-PR divergence through the summarizer's `doc_targets[].page_hint`.

Layout:

  fake_pr_summarizer__pr{1,2,3}.json   distinct page_hint per PR
  fake_content_validator.json          blocks connectors/three.md only
  fake_page_author.json                shared; the runner writes at its own
                                       computed target_path, so only `ok` matters
  fake_source_collector.json           merge_sha values are PLACEHOLDERS — the
                                       test rewrites them to real commit SHAs

Expected outcome: pages one and two survive, three is reverted, and the
baseline advances to PR 2's merge_sha — strictly past the documented work,
strictly short of the blocked PR's window.
