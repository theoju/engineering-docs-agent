# live-repo fixture (seed only)

`seed.json` pins two SHAs from this repo's history (`last_sha` = v0.1.0, `head_sha` = main at CCE-6) so a future ticket can run a deterministic full `orchestrator_runner.run(...)` live smoke test.

It is **not used** by the initial CCE-6 live tests. CCE-6 lands two `dispatch_subagent` live tests (notifier + pr-summarizer) instead: an orchestrator-level smoke is hard to make deterministic without mocking GitHub PR enumeration, which would defeat the purpose of a live test. Two dispatch tests with different payload shapes give the same wiring-regression signal at lower cost.

When a future ticket extends to orchestrator-level live coverage, it consumes this seed (update the SHAs if they drift out of relevance).
