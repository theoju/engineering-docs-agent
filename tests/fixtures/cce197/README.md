# CCE-197 fixture — a real fact-checker answer that omits `ok`

`20260930T161538-fact-checker-no-ok.stdout.txt` is the verbatim stdout of one
fact-checker dispatch from nightly run 36741357748 (2026-09-30), captured from
workflow artifact `11110992556` before it expired.

Why it is kept: it is the payload that made the run report
`fact_checker_unavailable: docs/site-src/core/infrastructure/api-pod-security-hardening.md`.
It carries a `contradiction` verdict and one fully-populated finding — every
field the orchestrator reads — and omits only `ok`, which the orchestrator never
reads. The schema listed `ok` in `required`, so the whole answer was discarded.

Measured breakdown for that run: 16 dispatches, 16 parsed as JSON, 15 carried
`ok`, exactly 1 omitted it (this one). Of the 15 with `ok`, 12 were `consistent`
and 3 were `contradiction` — so 3 of 4 contradictions did include `ok`. The
omission is model variance, not a rule about contradiction verdicts, which is
why the fix is tolerance in the schema rather than a prompt change alone.

Consumed by `tests/orchestrator/test_fact_checker.py`.
