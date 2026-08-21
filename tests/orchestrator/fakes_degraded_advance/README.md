# fakes_degraded_advance — CCE-151 reproduction fixture

A copy of `../fakes/` with **`fake_page_author.json` deliberately absent**.

An absent fixture makes the page-author dispatch yield no usable output, which
is the dry-run equivalent of the agent being rate-limited or otherwise
prevented from answering — the same trigger as the CCE-127 incident, one
pipeline stage later. Every other agent stays valid, so PR #1 is admitted and
summarized normally and the run is **not** time-truncated.

Do not add `fake_page_author.json` here. Its absence IS the fixture.
