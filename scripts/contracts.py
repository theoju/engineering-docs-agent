"""Typed boundaries for subagent output. Schemas live in agents/schemas/."""

from __future__ import annotations
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
import json
import jsonschema

SCHEMAS_DIR = Path(__file__).parent.parent / "agents" / "schemas"


@dataclass(frozen=True)
class SourceCollectorResult:
    prs: list[dict]
    jira_issues: list[dict]
    error: str | None = None
    partial: bool = False


@dataclass(frozen=True)
class PrSummary:
    pr_number: int
    what_changed: str | None = None
    why: str | None = None
    breaking: bool = False
    doc_targets: list[dict] = None  # type: ignore[assignment]
    notes: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.doc_targets is None:
            object.__setattr__(self, "doc_targets", [])


@dataclass(frozen=True)
class PageAuthorResult:
    ok: bool
    path: str | None = None
    action: str | None = None
    diff_summary: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    passed: list[dict]
    failed: list[dict]


@dataclass(frozen=True)
class GapVerdict:
    pr_id: str
    needs_spec: bool | None  # CCE-125: None = "unjudged" (advisory, non-partial)
    reasoning: str = ""
    confidence: str = "medium"
    tier: str = "llm"


@dataclass(frozen=True)
class VerifyVerdict:
    verified: list[str]
    failed: list[str]
    build_status: str


@dataclass(frozen=True)
class NotifierResult:
    slack_ok: bool
    email_ok: bool
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            object.__setattr__(self, "errors", [])


@dataclass(frozen=True)
class FactCheckerResult:
    # CCE-197: `verdict` leads and `ok` carries a default because the schema no
    # longer requires `ok`. validate_and_parse builds this as
    # ``cls(**{f.name: raw[f.name] for f in fields(cls) if f.name in raw})``, so
    # an absent `ok` against a no-default field would raise TypeError here — an
    # uncaught crash, strictly worse than the caught ValidationError it
    # replaces. Reordering is safe: this class is only ever built by keyword.
    verdict: str
    ok: bool | None = None
    page: str | None = None
    findings: list[dict] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.findings is None:
            object.__setattr__(self, "findings", [])
        # An absent `ok` means the agent answered and said nothing about
        # success, so derive it from `error` instead of guessing. An `ok` the
        # agent did supply — including False — is authoritative and is never
        # overwritten, which keeps the documented failure payload meaningful.
        if self.ok is None:
            object.__setattr__(self, "ok", self.error is None)


_DATACLASS_BY_NAME: dict[str, type] = {
    "source-collector": SourceCollectorResult,
    "pr-summarizer": PrSummary,
    "page-author": PageAuthorResult,
    "content-validator": ValidationResult,
    "gap-detector": GapVerdict,
    "publish-verifier": VerifyVerdict,
    "notifier": NotifierResult,
    "fact-checker": FactCheckerResult,
}


def validate_and_parse(name: str, raw: dict) -> tuple[Any | None, list[str]]:
    schema_path = SCHEMAS_DIR / f"{name.replace('-', '_')}.schema.json"
    if not schema_path.exists():
        return None, [f"schema_missing: {name}"]
    schema = json.loads(schema_path.read_text())
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as e:
        return None, [f"schema_invalid: {name}: {e.message}"]
    cls = _DATACLASS_BY_NAME.get(name)
    if cls is None:
        return None, [f"dataclass_missing: {name}"]
    kwargs = {f.name: raw[f.name] for f in fields(cls) if f.name in raw}
    return cls(**kwargs), []
