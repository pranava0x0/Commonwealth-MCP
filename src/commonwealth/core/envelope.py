"""The provenance/evidence envelope every tool returns.

Contract: design/provenance-envelope.md (revised 2026-08-26 — dimensional
coverage, explicit evidence refs). This module is the wire truth; the JSON
Schema committed at schemas/envelope.schema.json is generated from these
models and a test keeps the two identical.

Serialization rules (§ 1/§ 4.1 of the spec):
- absent-means-false / absent-means-none fields are dropped when empty
  (`requires_user_choice`, `next_actions`, `resources`, `conflict`);
- `warnings` is always present, often [];
- execution provenance rides under the reserved `_execution` key.
"""
from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer

ENVELOPE_VERSION = "1"

# Soft budget from design/provenance-envelope.md § 1.1; the contract test
# enforces it over fixtures and prints measured sizes.
DATA_TOKEN_BUDGET = 2000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistryCoverage(str, enum.Enum):
    covered = "covered"
    partial = "partial"
    none = "none"
    unknown = "unknown"


class ExecutionCoverage(str, enum.Enum):
    complete = "complete"
    partial = "partial"
    failed = "failed"


class PaginationCoverage(str, enum.Enum):
    complete = "complete"
    truncated = "truncated"
    unknown = "unknown"


class SourceClaimCoverage(str, enum.Enum):
    complete = "complete"
    partial = "partial"
    unknown = "unknown"


class ResultCoverage(str, enum.Enum):
    hit = "hit"
    empty = "empty"


class AuthorityLevel(str, enum.Enum):
    primary = "primary"
    official_secondary = "official_secondary"
    official_derived = "official_derived"
    third_party = "third_party"
    unverified = "unverified"


class AccessPath(str, enum.Enum):
    live = "live"
    cache = "cache"
    index = "index"


class RawRecovery(str, enum.Enum):
    available = "available"
    forbidden_by_terms = "forbidden_by_terms"
    expired = "expired"


class WarningCode(str, enum.Enum):
    """Adding a value is a reviewed change (spec § 5)."""

    screening_only = "screening_only"
    stale_source = "stale_source"
    freshness_unavailable = "freshness_unavailable"
    boundary_precision = "boundary_precision"
    alias_match = "alias_match"
    mixed_vintages = "mixed_vintages"
    terms_note = "terms_note"
    sensitive_public_data = "sensitive_public_data"
    insecure_transport = "insecure_transport"
    truncated_inline = "truncated_inline"


class JurisdictionGap(_Strict):
    jurisdiction: str
    reason: str


class TimeRange(_Strict):
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SourceFailure(_Strict):
    source_id: str
    error: str
    detail: str


class Coverage(_Strict):
    """Five independent dimensions; never collapse them into one status."""

    registry: RegistryCoverage
    execution: ExecutionCoverage
    pagination: PaginationCoverage = PaginationCoverage.unknown
    source_claim: SourceClaimCoverage = SourceClaimCoverage.unknown
    result: ResultCoverage
    jurisdictions_searched: list[str] = Field(default_factory=list)
    jurisdictions_unavailable: list[JurisdictionGap] = Field(default_factory=list)
    time_range: TimeRange | None = None
    source_failures: list[SourceFailure] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)


class SourceEntry(_Strict):
    id: str
    source_id: str
    publisher: str
    system: str
    dataset: str
    jurisdiction: str
    authority_level: AuthorityLevel
    access_path: AccessPath
    source_updated_at: str | None
    retrieved_at: str
    cache_age_seconds: int


class Evidence(_Strict):
    id: str
    source_ref: str
    record_id: str
    # A wrong link is worse than no link: locator is emitted only when the
    # platform actually produces one, never derived by guesswork.
    locator: str | None = None
    retrieved_at: str
    effective_at: str | None = None
    transformations: list[str] = Field(default_factory=list)
    payload_hash: str | None = None
    raw_recovery: RawRecovery = RawRecovery.available


class WarningNote(_Strict):
    code: WarningCode
    message: str
    source_id: str | None = None


class NextAction(_Strict):
    finding: str
    suggested_capability: str
    reason: str


class ResourceRef(_Strict):
    uri: str
    media_type: str | None = None
    description: str | None = None


class ExecutionProvenance(_Strict):
    server: str
    server_version: str
    tool: str
    tool_contract_version: str
    envelope_version: str = ENVELOPE_VERSION
    adapters: dict[str, str] = Field(default_factory=dict)
    registry_revision: str
    request_id: str


class Envelope(_Strict):
    data: dict[str, Any]
    provenance: list[SourceEntry] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    coverage: Coverage
    warnings: list[WarningNote] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    resources: list[ResourceRef] = Field(default_factory=list)
    requires_user_choice: bool = False
    execution: ExecutionProvenance | None = None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        """The schema must describe the WIRE shape the serializer emits
        (clients validate structured content against it, strictly): the
        `execution` field rides as `_execution` on the wire."""
        schema = handler(core_schema)
        props = schema.get("properties", {})
        if "execution" in props:
            props["_execution"] = props.pop("execution")
        return schema

    @model_serializer(mode="wrap")
    def _wire(self, handler: Any) -> dict[str, Any]:
        out: dict[str, Any] = handler(self)
        execution = out.pop("execution", None)
        if execution is not None:
            out["_execution"] = execution
        if not out.get("requires_user_choice"):
            out.pop("requires_user_choice", None)
        for optional_list in ("next_actions", "resources"):
            if not out.get(optional_list):
                out.pop(optional_list, None)
        # Coverage optionals drop when empty; the five dimensions always stay.
        cov = out.get("coverage")
        if isinstance(cov, dict):
            for k in ("time_range", "jurisdictions_unavailable",
                      "source_failures", "known_limitations",
                      "jurisdictions_searched"):
                if not cov.get(k):
                    cov.pop(k, None)
        return out

    def data_token_estimate(self) -> int:
        """Rough tokens for `data` (~4 chars/token). An estimate for budget
        tests, not an exact count; the test prints it so it stays falsifiable."""
        return len(json.dumps(self.data, separators=(",", ":"))) // 4

    @classmethod
    def wire_schema(cls) -> dict[str, Any]:
        """The published wire schema (spec § 4.1). Note the serializer's
        absent-when-empty fields are optional here by construction."""
        schema = cls.model_json_schema()
        schema["title"] = "CommonwealthEnvelope"
        schema["$comment"] = (
            f"envelope_version {ENVELOPE_VERSION}; generated from "
            "commonwealth.core.envelope — edit the models, not this file."
        )
        return schema


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
