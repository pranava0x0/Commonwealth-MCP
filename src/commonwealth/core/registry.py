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

# The adapter type and probe name a manifest carries when it describes no
# endpoint at all (design/source-registry.md § 6.3). Both are refused at the
# activation gate, so an inventory row can never be queried or probed.
INVENTORY_ADAPTER = "none"
NO_PROBE = "none"
# The probe every ArcGIS manifest declares, and the keys its `expect`
# block is read for. `min_features` is the floor per layer; the rest are
# sample records the recorder uses. A key outside this set is not an
# error the probe reports, it is a floor that silently becomes 1 (two
# manifests shipped that way; found in review of PR #56).
ARCGIS_COUNT_PROBE = "arcgis_layer_count"
ARCGIS_PROBE_EXPECT_KEYS = frozenset(
    {"min_features", "sample_pin", "sample_point", "also_record"})


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
    # Optional at the schema level, required to activate (checked in
    # validate_manifest). A `proposed` manifest is inventory whose terms
    # nobody has read yet; making the field mandatory would force it to
    # invent a review date, which is worse than admitting there is none.
    terms_reviewed_at: str | None = None
    # What the terms review could NOT establish, in the publisher's terms
    # rather than this project's. Set it and every envelope citing this
    # source carries a terms_note warning quoting it, so a gap recorded in
    # a manifest becomes a disclosure at the point of use instead of a
    # caveat only a contributor ever reads.
    terms_gap: str | None = None
    data_classification: DataClassification = DataClassification.open
    # Whether the result store may hold this publisher's bytes past the
    # request (decision 0013; core/results.py enforces it at write time).
    # Defaults to allowed because every source registered so far publishes
    # open data with no retention condition, and a default of `forbidden`
    # would silently disable result handles for all of them. A reviewer
    # who reads a retention condition in the terms sets this and records
    # the clause in `terms_notes`.
    retention: str = "allowed"  # allowed | forbidden
    exposure_allowlist: list[str] | None = None
    classification_reviewed_by: str | None = None
    classification_reviewed_at: str | None = None
    insecure_transport: bool = False
    credential_ref: str | None = None


# How often a publisher says it updates, in seconds. The vocabulary is
# what manifests already use; `unknown` is not here because a source that
# does not say how often it updates cannot be measured against its own
# promise, and inventing a number for it would be this project deciding
# what "current" means for someone else's data (GitHub issue #57).
CADENCE_SECONDS = {
    "continuous": 3600,
    "daily": 86_400,
    "weekly": 7 * 86_400,
    "monthly": 30 * 86_400,
    "quarterly": 90 * 86_400,
    "annually": 365 * 86_400,
}

# How far past its own cadence a source may drift before an answer says
# so. A grace factor rather than a hard edge: a daily feed retrieved on
# Monday still showing Friday's edit is a weekend, not a fault. Two is a
# choice — the smallest multiple that does not fire on ordinary slippage
# — and it is written here, once, rather than left implicit in a
# comparison.
CADENCE_GRACE = 2

# What a manifest writes for `cadence_source` when nobody recorded where
# the cadence came from. The design vocabulary is stated | observed |
# unknown; in practice manifests write the statement out ("Stated by the
# publisher in the service description: ...") and this is the one value
# that is a sentinel rather than a record.
NO_CADENCE_PROVENANCE = "unknown"


class Freshness(_Strict):
    expected_cadence: str
    cadence_source: str  # stated | observed | unknown
    ttl_hint_seconds: int

    def cadence_has_provenance(self) -> bool:
        """Whether the manifest says where its cadence came from.

        `expected_cadence: daily` with `cadence_source: unknown` is a
        figure somebody wrote down without recording who said it. That
        is not the publisher's promise, so it is not a yardstick this
        project may hold the publisher to. Found in review of PR #56:
        two manifests declare `daily` that way, and the staleness
        warning was telling callers the publisher had described that
        schedule.
        """
        source = (self.cadence_source or "").strip().lower()
        return bool(source) and source != NO_CADENCE_PROVENANCE

    def stale_after_seconds(self) -> int | None:
        """When this publisher's own data should be called stale, or None.

        None for a cadence this project does not recognise, `unknown`
        included, and None for a cadence whose provenance is unknown:
        either way there is no promise of the publisher's to measure
        against, and `freshness_unavailable` already covers a source
        that reports no vintage at all. The two warnings answer
        different questions — "we do not know how old this is" and "we
        know, and it is older than the publisher said it would be".
        """
        if not self.cadence_has_provenance():
            return None
        base = CADENCE_SECONDS.get((self.expected_cadence or "").lower())
        return base * CADENCE_GRACE if base else None


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
    # What an active source must carry that inventory need not. Each was
    # previously mandatory for every manifest, so a `proposed` row could
    # only validate by inventing a terms review that never happened, a
    # probe with nothing to probe, and a capability claim with no endpoint
    # behind it. Checking them at the activation gate instead lets an
    # inventory row record what it knows and still validate.
    if active and not manifest.access.terms_reviewed_at:
        bad("declared_state=active requires terms_reviewed_at; a source "
            "cannot be queried on terms nobody has read")
    if active and manifest.adapter.type == INVENTORY_ADAPTER:
        bad(f"adapter type {INVENTORY_ADAPTER!r} names the absence of an "
            "endpoint and cannot be active; it is inventory only")
    if active and manifest.health.probe == NO_PROBE:
        bad(f"declared_state=active requires a real health probe, not "
            f"{NO_PROBE!r}")
    if active and not manifest.capabilities:
        bad("declared_state=active requires at least one capability; an "
            "active source with none can never be selected")
    if not active and manifest.capabilities:
        # A capability id is a routing promise. Selection already filters
        # on declared_state, so a proposed manifest declaring one is not
        # dangerous — it is just untrue, and `sources stats` counts
        # capability coverage from these rows.
        bad("only an active manifest may declare capabilities; record the "
            "intended capability in authority_notes until the source is "
            "wired up")
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

    if manifest.health.probe == ARCGIS_COUNT_PROBE:
        expect = manifest.health.expect or {}
        unknown_keys = sorted(set(expect) - ARCGIS_PROBE_EXPECT_KEYS)
        if unknown_keys:
            bad(f"health.expect for probe {ARCGIS_COUNT_PROBE!r} is not read "
                f"for {unknown_keys}, so every floor would fall back to 1; "
                "declare floors as min_features: {<layer>: <count>}")
        floors = expect.get("min_features")
        layers = set(manifest.adapter.model_dump().get("layers") or {})
        if isinstance(floors, dict):
            stray = sorted(set(floors) - layers)
            if stray:
                bad("health.expect.min_features names layers this manifest "
                    f"does not declare: {stray}; declared: {sorted(layers)}")
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 1
                   for v in floors.values()):
                bad("health.expect.min_features values must be whole "
                    "numbers of at least 1")
        elif floors is not None and (isinstance(floors, bool)
                                     or not isinstance(floors, int)):
            bad("health.expect.min_features must be a whole number or a "
                "map of layer to whole number")

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

    def servable_capabilities(self) -> set[str]:
        """Capabilities at least one selectable source declares, anywhere.

        The activation rules are `select`'s, minus the jurisdiction filter:
        a capability is servable when some active, automatable source that
        is not known to be down answers it. Coverage in a particular
        locality is a different question, and the tools answer it per
        query.
        """
        return {c
                for m in self.manifests.values()
                if m.lifecycle.declared_state == DeclaredState.active
                and m.access.automation_status in ACTIVATABLE
                and self.operational(m.id) != OperationalState.unavailable
                for c in m.capability_ids()}

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
