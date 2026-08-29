"""Government Source Registry: manifest models, loader, activation gates,
and top-two source selection.

Contract: design/source-registry.md (revised 2026-08-26). Selection follows
../../../design/architecture.md decision 0005 as Chosen (architect override): no central ranking, no derived
primary — pick the top two selectable candidates for a (jurisdiction,
capability), query both, surface both. `authority_level` orders the *which
two* question only.

Adapter parameter blocks validate against the adapter's own registered params
model (rule 3 of the spec); adapters register themselves via
`register_adapter_params` when imported.
"""
from __future__ import annotations

import enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .envelope import AuthorityLevel
from .errors import InvalidQuery


class AutomationStatus(str, enum.Enum):
    permitted = "permitted"
    public_api = "public_api"
    public_download = "public_download"
    manual_review_required = "manual_review_required"
    restricted = "restricted"
    do_not_automate = "do_not_automate"
    unknown = "unknown"


ACTIVATABLE = {AutomationStatus.permitted, AutomationStatus.public_api,
               AutomationStatus.public_download}


class DataClassification(str, enum.Enum):
    open = "open"
    sensitive_public = "sensitive_public"
    restricted = "restricted"


class DeclaredState(str, enum.Enum):
    proposed = "proposed"
    active = "active"
    retired = "retired"


class OperationalState(str, enum.Enum):
    """Runtime state, never stored in manifests (spec § 1 lifecycle note)."""

    healthy = "healthy"
    impaired = "impaired"
    unavailable = "unavailable"
    unknown = "unknown"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Publisher(_Strict):
    agency: str
    authority_level: AuthorityLevel


class CapabilityDecl(_Strict):
    id: str
    tool_hint: str | None = None


class AdapterBlock(BaseModel):
    """`type` is fixed; everything else belongs to the adapter's params model
    and is validated against it when that adapter is registered."""

    model_config = ConfigDict(extra="allow")
    type: str


class Access(_Strict):
    mode: str  # anonymous | api_key | oauth | restricted
    automation_status: AutomationStatus
    terms_url: str
    terms_notes: str
    terms_reviewed_at: str
    data_classification: DataClassification = DataClassification.open
    exposure_allowlist: list[str] | None = None
    classification_reviewed_by: str | None = None
    classification_reviewed_at: str | None = None
    insecure_transport: bool = False
    credential_ref: str | None = None


class Freshness(_Strict):
    expected_cadence: str
    cadence_source: str  # stated | observed | unknown
    ttl_hint_seconds: int


class CoverageDecl(_Strict):
    geography: str
    temporal: str
    known_limitations: list[str] = Field(default_factory=list)


class HealthDecl(_Strict):
    probe: str
    expect: dict = Field(default_factory=dict)


class Lifecycle(_Strict):
    declared_state: DeclaredState
    added: str
    last_verified: str
    verified_by: str


class SourceManifest(_Strict):
    id: str
    name: str
    jurisdiction: str
    publisher: Publisher
    domains: list[str]
    capabilities: list[CapabilityDecl]
    adapter: AdapterBlock
    access: Access
    freshness: Freshness
    coverage: CoverageDecl
    authority_notes: str
    health: HealthDecl
    lifecycle: Lifecycle

    def capability_ids(self) -> set[str]:
        return {c.id for c in self.capabilities}


# --- adapter params validation hook ---------------------------------------

_ADAPTER_PARAMS: dict[str, type[BaseModel]] = {}


def register_adapter_params(adapter_type: str, model: type[BaseModel]) -> None:
    _ADAPTER_PARAMS[adapter_type] = model


def registered_adapter_types() -> set[str]:
    return set(_ADAPTER_PARAMS)


# --- validation ------------------------------------------------------------

class ManifestProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    problem: str


def validate_manifest(manifest: SourceManifest, path: str,
                      known_capabilities: set[str],
                      known_jurisdictions: set[str]) -> list[ManifestProblem]:
    """Activation-gate rules from design/source-registry.md § 3 plus
    referential checks. Returns problems; empty means valid."""
    problems: list[ManifestProblem] = []

    def bad(msg: str) -> None:
        problems.append(ManifestProblem(path=path, problem=msg))

    active = manifest.lifecycle.declared_state == DeclaredState.active
    status = manifest.access.automation_status
    if active and status not in ACTIVATABLE:
        bad(f"declared_state=active requires automation_status in "
            f"{sorted(s.value for s in ACTIVATABLE)}, got {status.value!r}")
    if manifest.access.data_classification == DataClassification.restricted \
            and active:
        bad("data_classification=restricted cannot be active in V1")
    if manifest.access.data_classification == DataClassification.sensitive_public:
        if not manifest.access.exposure_allowlist:
            bad("sensitive_public requires a field-level exposure_allowlist")
        if not (manifest.access.classification_reviewed_by
                and manifest.access.classification_reviewed_at):
            bad("sensitive_public requires classification_reviewed_by "
                "and classification_reviewed_at")
    if manifest.jurisdiction not in known_jurisdictions:
        bad(f"jurisdiction {manifest.jurisdiction!r} is not in the "
            "jurisdiction table")
    unknown_caps = manifest.capability_ids() - known_capabilities
    if unknown_caps:
        bad(f"capabilities not in the vocabulary: {sorted(unknown_caps)}")

    params_model = _ADAPTER_PARAMS.get(manifest.adapter.type)
    if params_model is None:
        bad(f"adapter type {manifest.adapter.type!r} has no registered "
            "adapter (import commonwealth.adapters before validating)")
    else:
        try:
            params_model.model_validate(
                manifest.adapter.model_dump(exclude={"type"}))
        except ValidationError as err:
            bad(f"adapter params invalid for {manifest.adapter.type!r}: "
                f"{err.errors()[0]['loc']}: {err.errors()[0]['msg']}")
    return problems


# --- the registry ----------------------------------------------------------

class SourceRegistry:
    def __init__(self, manifests: list[SourceManifest],
                 capability_vocab: set[str], revision: str) -> None:
        self.manifests = {m.id: m for m in manifests}
        if len(self.manifests) != len(manifests):
            raise ValueError("duplicate source ids in registry")
        self.capability_vocab = capability_vocab
        self.revision = revision
        self._operational: dict[str, OperationalState] = {}

    @classmethod
    def load(cls, sources_dir: Path) -> "SourceRegistry":
        vocab_file = sources_dir / "capabilities.yaml"
        if not vocab_file.exists():
            raise FileNotFoundError(f"missing capability vocabulary: {vocab_file}")
        vocab_doc = yaml.safe_load(vocab_file.read_text())
        vocab = {c["id"] for c in vocab_doc["capabilities"]}

        paths = [p for p in sorted(sources_dir.rglob("*.yaml"))
                 if p.name != "capabilities.yaml"
                 and "jurisdictions" not in p.parts]
        manifests = [SourceManifest.model_validate(yaml.safe_load(p.read_text()))
                     for p in paths]

        # Activation-gate enforcement belongs to the runtime path, not only
        # `commonwealth sources validate` / CI: a manifest that fails its
        # gates (design/source-registry.md § 3 — e.g. declared_state=active
        # with automation_status outside ACTIVATABLE, or restricted+active)
        # must never become selectable just because the CLI check was
        # skipped for one load.
        from .jurisdiction import JurisdictionTable
        known_jurisdictions = JurisdictionTable.load(
            sources_dir / "jurisdictions").ids()
        problems = [prob for path, manifest in zip(paths, manifests)
                   for prob in validate_manifest(manifest, str(path), vocab,
                                                 known_jurisdictions)]
        if problems:
            detail = "; ".join(f"{p.path}: {p.problem}" for p in problems)
            raise ValueError(
                f"{len(problems)} source manifest(s) failed activation "
                f"gates: {detail}")

        revision = max((m.lifecycle.last_verified for m in manifests),
                       default="unknown")
        return cls(manifests, vocab, revision)

    # Runtime health overlay (never a manifest field).
    def set_operational(self, source_id: str, state: OperationalState) -> None:
        self._operational[source_id] = state

    def operational(self, source_id: str) -> OperationalState:
        return self._operational.get(source_id, OperationalState.unknown)

    def get(self, source_id: str) -> SourceManifest | None:
        return self.manifests.get(source_id)

    def covers_capability_anywhere(self, capability: str) -> bool:
        if capability not in self.capability_vocab:
            raise InvalidQuery(
                f"capability {capability!r} is not in the vocabulary; "
                f"known: {sorted(self.capability_vocab)}")
        return any(capability in m.capability_ids()
                   for m in self.manifests.values())

    def select(self, capability: str,
               jurisdiction_ids: list[str]) -> list[SourceManifest]:
        """../../../design/architecture.md decision 0005 (Chosen): the top TWO selectable sources for the
        capability across the given jurisdiction stack. Ordering exists only
        to answer *which two* — authority_level, then freshness cadence hint.
        Callers query every returned source and surface every result."""
        if capability not in self.capability_vocab:
            raise InvalidQuery(f"capability {capability!r} is not in the "
                               "vocabulary")
        authority_order = {AuthorityLevel.primary: 0,
                           AuthorityLevel.official_secondary: 1,
                           AuthorityLevel.official_derived: 2,
                           AuthorityLevel.third_party: 3,
                           AuthorityLevel.unverified: 4}
        candidates = [
            m for m in self.manifests.values()
            if capability in m.capability_ids()
            and m.jurisdiction in jurisdiction_ids
            and m.lifecycle.declared_state == DeclaredState.active
            and m.access.automation_status in ACTIVATABLE
            and self.operational(m.id) != OperationalState.unavailable
        ]
        candidates.sort(key=lambda m: (
            authority_order[m.publisher.authority_level],
            m.freshness.ttl_hint_seconds, m.id))
        return candidates[:2]

    def unavailable_for(self, capability: str,
                        jurisdiction_ids: list[str]) -> list[tuple[str, str]]:
        """(jurisdiction, reason) pairs explaining why nothing was selectable —
        the explanation behind coverage.jurisdictions_unavailable."""
        out: list[tuple[str, str]] = []
        for jid in jurisdiction_ids:
            js = [m for m in self.manifests.values()
                  if m.jurisdiction == jid and capability in m.capability_ids()]
            if not js:
                out.append((jid, "no_registered_source"))
                continue
            selectable = [m for m in js
                          if m.lifecycle.declared_state == DeclaredState.active
                          and m.access.automation_status in ACTIVATABLE
                          and self.operational(m.id) != OperationalState.unavailable]
            if not selectable:
                if any(self.operational(m.id) == OperationalState.unavailable
                       for m in js):
                    out.append((jid, "source_unavailable"))
                else:
                    out.append((jid, "source_not_activated"))
        return out
