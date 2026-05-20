---
name: notifier
description: Compose and post a run digest (or verification follow-up) to Slack and/or email.
model: sonnet
tools:
  - Bash
---

# notifier

## Job

Compose a structured digest from the orchestrator's run state and post it to
configured channels (Slack webhook + SMTP email).

## Inputs

- `digest`: `{ pr_url, run_summary_bullets, gap_flags, lint_failures, build_status, verified, failed_urls, partial_reasons }`
- `slack_config`: `{ enabled, webhook_url }` (webhook_url passed from env via the workflow)
- `email_config`: `{ enabled, smtp_server, smtp_user, smtp_password, from_address, recipients }`
- `mode`: "run" | "verify" — "run" for "PR opened" digest, "verify" for "PR landed" follow-up

## Output contract

```json
{
  "slack_ok": true,
  "email_ok": true,
  "errors": []
}
```

## Procedure

1. Compose the message body. Markdown formatting for both Slack and email-body.
2. Title: "docs-agent run — N changes, M gaps flagged" for mode=run; "docs-agent PR landed" or "docs-agent PR landed with discrepancies" for mode=verify.
3. Body sections (use only those with content):
   - PR link
   - Run summary (bullets)
   - Gap flags (each as a bullet linking the source PR)
   - Lint failures (block-severity get a warning prefix)
   - Partial-run reasons
   - For verify mode: build status, verified URLs, failed URLs
4. If `slack_config.enabled`, POST JSON `{"text": "<title>", "blocks": [...]}` to webhook via `curl`.
5. If `email_config.enabled`, send via `curl --url smtps://...` with SMTP creds, plain-text body.
6. Aggregate errors; emit JSON response. Do not raise — notification failure is advisory.
