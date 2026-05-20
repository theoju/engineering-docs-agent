---
name: publish-verifier
description: After a docs PR merges, poll the host build workflow then verify pages are live.
model: sonnet
tools:
  - Bash
  - WebFetch
---

# publish-verifier

## Job

After a docs-agent PR merges:

1. Poll the host's downstream build workflow until success or timeout.
2. Derive live URLs for changed pages from config's `publishing.base_url` and `url_map_rule`.
3. Fetch each URL; confirm 200 and a content fingerprint matches.

## Inputs

- `merged_pr_number`: int
- `changed_paths`: list of repo-relative paths
- `publishing_config`: `{ base_url, build_workflow, url_map_rule, verify_timeout_seconds }`
- `repo`: `{ owner, name }`

## Output contract

```json
{
  "verified": [{ "path": "...", "url": "...", "status": 200 }],
  "failed": [{ "path": "...", "url": "...", "status": 404, "reason": "..." }],
  "build_status": "success"
}
```

`build_status`: "success" | "failure" | "timeout".

## Procedure

1. Wait for `build_workflow` run with `event=push, head_branch=main` after `merged_pr_number` merge time. Poll `gh run list --workflow <build_workflow>` every 30s.
2. On success, derive each URL: `url_map_rule=standard` means `docs/site-src/foo/bar.md` → `<base_url>/foo/bar/` (strip the configured `source_dir` prefix, drop `.md`, add trailing slash). For `url_map_rule=custom`, use `publishing_config.url_regex` (a sed-like substitution).
3. For each URL, `curl -s -o /tmp/page.html -w "%{http_code}" <url>`. Status 200 = verified. Other = failed.
4. Optional fingerprint: compute a SHA of a content marker (e.g. the page title) and verify it appears in the body.
5. On timeout: emit `build_status: "timeout"` and `failed: [...]` for unverified paths.

## Failure handling

If `gh run list` returns no runs, retry until timeout, then emit `build_status: "timeout"`.
