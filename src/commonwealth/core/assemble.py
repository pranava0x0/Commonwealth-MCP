"""EnvelopeBuilder: one uniform way for tools to assemble envelopes.

Keeps the disclosure rules in one place: source entries auto-carry the
freshness_unavailable warning when a publisher exposes no update date;
evidence must reference a registered source entry; coverage dimensions are
explicit at build time, never defaulted into optimism.
"""
from __future__ import annotations

import uuid

from .envelope import (AccessPath, AuthorityLevel, Coverage, Envelope,
                       Evidence, ExecutionProvenance, JurisdictionGap,
                       NextAction, RawRecovery, RegistryCoverage,
                       ResourceRef, ResultCoverage, SourceEntry,
                       SourceFailure, WarningCode, WarningNote)


class EnvelopeBuilder:
    def __init__(self, *, server: str, server_version: str, tool: str,
                 contract_version: str, registry_revision: str,
                 adapters: dict[str, str]) -> None:
        self._execution = ExecutionProvenance(
            server=server, server_version=server_version, tool=tool,
            tool_contract_version=contract_version,
            adapters=adapters, registry_revision=registry_revision,
            request_id=uuid.uuid4().hex)
        self._sources: list[SourceEntry] = []
        self._evidence: list[Evidence] = []
        self._warnings: list[WarningNote] = []
        self._next: list[NextAction] = []
        self._resources: list[ResourceRef] = []

    @property
    def tool_name(self) -> str:
        """The tool this envelope is for. Read by the result store, which
        records it so an expired handle can say which call to re-run."""
        return self._execution.tool

    def add_source(self, *, source_id: str, publisher: str, system: str,
                  dataset: str, jurisdiction: str,
                  authority_level: AuthorityLevel, access_path: AccessPath,
                  source_updated_at: str | None, retrieved_at: str,
                  cache_age_seconds: int,
                  warn_on_missing_freshness: bool = True,
                  terms_gap: str | None = None) -> str:
        ref = f"source_{len(self._sources) + 1:02d}"
        self._sources.append(SourceEntry(
            id=ref, source_id=source_id, publisher=publisher, system=system,
            dataset=dataset, jurisdiction=jurisdiction,
            authority_level=authority_level, access_path=access_path,
            source_updated_at=source_updated_at, retrieved_at=retrieved_at,
            cache_age_seconds=cache_age_seconds))
        if source_updated_at is None and warn_on_missing_freshness:
            self.warn(WarningCode.freshness_unavailable,
                      "The publisher exposes no machine-readable update date "
                      "for this layer; retrieval time is known, data vintage "
                      "is not.", source_id)
        if terms_gap and not any(
                w.code == WarningCode.terms_note and w.source_id == source_id
                for w in self._warnings):
            self.warn(WarningCode.terms_note, terms_gap, source_id)
        return ref

    def add_evidence(self, *, source_ref: str, record_id: str,
                     retrieved_at: str, transformations: list[str],
                     payload_hash: str | None = None,
                     locator: str | None = None,
                     raw_recovery: RawRecovery = RawRecovery.available) -> str:
        if source_ref not in {s.id for s in self._sources}:
            raise ValueError(f"evidence references unknown source entry "
                             f"{source_ref!r}")
        ref = f"evidence_{len(self._evidence) + 1:02d}"
        self._evidence.append(Evidence(
            id=ref, source_ref=source_ref, record_id=record_id,
            locator=locator, retrieved_at=retrieved_at,
            transformations=transformations, payload_hash=payload_hash,
            raw_recovery=raw_recovery))
        return ref

    def warn(self, code: WarningCode, message: str,
             source_id: str | None = None) -> None:
        self._warnings.append(WarningNote(code=code, message=message,
                                          source_id=source_id))

    def add_resource(self, ref: ResourceRef) -> str:
        """Attach a handle to a payload too large to return inline.

        The envelope's `resources` field existed from the start and had no
        way to be filled, so it was always empty (decision 0013; GitHub
        issue #33). Callers build the ref through
        `core.results.resource_ref()`, which carries the expiry into the
        description.
        """
        self._resources.append(ref)
        return ref.uri

    def next_action(self, finding: str, capability: str, reason: str) -> None:
        if len(self._next) >= 3:  # spec § 6: at most 3
            return
        self._next.append(NextAction(finding=finding,
                                     suggested_capability=capability,
                                     reason=reason))

    def build(self, data: dict, coverage: Coverage, *,
              requires_user_choice: bool = False) -> Envelope:
        return Envelope(data=data, provenance=self._sources,
                        evidence=self._evidence, coverage=coverage,
                        warnings=self._warnings, next_actions=self._next,
                        resources=self._resources,
                        requires_user_choice=requires_user_choice,
                        execution=self._execution)


def gap(jurisdiction: str, reason: str) -> JurisdictionGap:
    return JurisdictionGap(jurisdiction=jurisdiction, reason=reason)


def failure(source_id: str, error: str, detail: str) -> SourceFailure:
    return SourceFailure(source_id=source_id, error=error, detail=detail)


def result_dim(record_count: int) -> ResultCoverage:
    return ResultCoverage.hit if record_count > 0 else ResultCoverage.empty


def new_request_id() -> str:
    return uuid.uuid4().hex


# The escalation hint a registry gap carries (design/provenance-envelope.md
# § 10, and the trap #28's Tier-2 suite scores). It names a tool rather
# than a capability, which is the one exception to § 6's rule: the registry
# tools read the registry itself rather than a registered source, so
# `registry.search_sources` has no capability id to name instead. Recorded
# in § 6 with the same reasoning, 2026-09-01.
REGISTRY_GAP_ACTION = "registry.search_sources"


def selection_coverage(sources, capability: str, stack: list[str],
                       selected: list, builder=None
                       ) -> tuple[RegistryCoverage, list]:
    """Shared across domains: the registry-coverage dimension and any
    jurisdiction gaps for a capability/jurisdiction-stack selection.
    `sources` is a SourceRegistry; `selected` is what it already returned
    from `.select()` for the same (capability, stack).

    Pass `builder` and a total registry gap also emits its escalation
    hint. It lands here rather than in each tool because every tool that
    can report `registry: none` reaches this function to decide it, and a
    hint added per tool is a hint some tool forgets.
    """
    if selected:
        return RegistryCoverage.covered, []
    gaps = [gap(j, reason) for j, reason
           in sources.unavailable_for(capability, stack)]
    if gaps and all(g.reason == "no_registered_source" for g in gaps):
        if builder is not None:
            builder.next_action(
                finding="registry_gap",
                capability=REGISTRY_GAP_ACTION,
                reason=(f"No source is registered for {capability} in "
                        f"{', '.join(g.jurisdiction for g in gaps)}. The "
                        "records may well exist; this project has no "
                        "registered place to read them. Search the "
                        "registry for what is covered, and treat the gap "
                        "as unknown rather than as an absence."))
        return RegistryCoverage.none, gaps
    return RegistryCoverage.partial, gaps
