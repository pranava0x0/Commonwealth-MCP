"""Per-call audit records, derived from the envelope.

The envelope already carries the trail (sources consulted, evidence,
coverage, execution provenance); an audit record is its operational
summary — one JSON object per tool call, safe to log and to publish.
Structural minimization (DECISIONS.md 0014 § 3) applies here the same as in
adapter logs: when any consulted source is sensitive_public, argument
VALUES are dropped and only argument names remain.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .envelope import Envelope, utc_now_iso


class AuditSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    access_path: str
    cache_age_seconds: int
    authority_level: str


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: str
    request_id: str
    tool: str
    server: str
    server_version: str
    duration_ms: int
    args: dict[str, Any] | None
    arg_names: list[str]
    coverage: dict[str, str]
    sources: list[AuditSource] = Field(default_factory=list)
    evidence_count: int
    warning_codes: list[str] = Field(default_factory=list)
    requires_user_choice: bool = False
    error: str | None = None
    registry_revision: str


def record_from_envelope(tool: str, args: dict[str, Any],
                         envelope: Envelope, duration_ms: int,
                         sensitive: bool = False) -> AuditRecord:
    execution = envelope.execution
    if execution is None:
        raise ValueError("envelope without execution provenance cannot be "
                         "audited — every tool path must attach it")
    cov = envelope.coverage
    shown_args = {k: v for k, v in args.items() if v is not None}
    return AuditRecord(
        ts=utc_now_iso(),
        request_id=execution.request_id,
        tool=tool,
        server=execution.server,
        server_version=execution.server_version,
        duration_ms=duration_ms,
        args=None if sensitive else shown_args,
        arg_names=sorted(args),
        coverage={
            "registry": cov.registry.value,
            "execution": cov.execution.value,
            "pagination": cov.pagination.value,
            "result": cov.result.value,
        },
        sources=[AuditSource(source_id=s.source_id,
                             access_path=s.access_path.value,
                             cache_age_seconds=s.cache_age_seconds,
                             authority_level=s.authority_level.value)
                 for s in envelope.provenance],
        evidence_count=len(envelope.evidence),
        warning_codes=sorted({w.code.value for w in envelope.warnings}),
        requires_user_choice=envelope.requires_user_choice,
        registry_revision=execution.registry_revision)


def error_record(tool: str, args: dict[str, Any], error_code: str,
                 duration_ms: int, server: str, server_version: str,
                 registry_revision: str, sensitive: bool = False
                 ) -> AuditRecord:
    """`sensitive` is registry-wide (RuntimeContext.has_sensitive_sources),
    not per-call: a failure can occur before it's known which source a call
    would have reached, so this errs conservative rather than assuming
    safe (DECISIONS.md 0014 § 3 structural minimization, same rule as the
    success path in record_from_envelope)."""
    return AuditRecord(
        ts=utc_now_iso(), request_id="", tool=tool, server=server,
        server_version=server_version, duration_ms=duration_ms,
        args=None if sensitive else args, arg_names=sorted(args),
        coverage={}, evidence_count=0, error=error_code,
        registry_revision=registry_revision)


class AuditLog:
    """Append-only JSONL sink. A process gets one; tests get a fresh one."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps(record.model_dump(mode="json"),
                                    separators=(",", ":")) + "\n")
