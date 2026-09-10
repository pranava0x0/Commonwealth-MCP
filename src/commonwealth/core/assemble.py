"""EnvelopeBuilder: one uniform way for tools to assemble envelopes.

Keeps the disclosure rules in one place: source entries auto-carry the
freshness_unavailable warning when a publisher exposes no update date;
evidence must reference a registered source entry; coverage dimensions are
explicit at build time, never defaulted into optimism.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from .envelope import (AccessPath, AuthorityLevel, Coverage, Envelope,
                       Evidence, ExecutionProvenance, JurisdictionGap,
                       NextAction, RawRecovery, RegistryCoverage,
                       ExecutionCoverage, PaginationCoverage,
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
                  terms_gap: str | None = None,
                  manifest=None) -> str:
        """`manifest` carries everything derived from the registered
        source: the terms gap to disclose, and the cadence a vintage is
        measured against.

        One argument rather than one per disclosure, because the
        alternative is what happened to `terms_gap` — it was threaded
        through as its own parameter and five of the seven call sites
        never passed it. Nothing was lost only because the three sources
        that declare a gap all happen to be reached by the two that did.
        A call site that hands over the manifest cannot forget the next
        disclosure that gets added here.
        """
        if manifest is not None and terms_gap is None:
            terms_gap = manifest.access.terms_gap
        ref = f"source_{len(self._sources) + 1:02d}"
        self._sources.append(SourceEntry(
            id=ref, source_id=source_id, publisher=publisher, system=system,
            dataset=dataset, jurisdiction=jurisdiction,
            authority_level=authority_level, access_path=access_path,
            source_updated_at=source_updated_at, retrieved_at=retrieved_at,
            cache_age_seconds=cache_age_seconds))
        if (source_updated_at is None and warn_on_missing_freshness
                # Once per source. A tool reading two layers of one
                # service adds the entry twice, and the same sentence
                # twice reads as two separate problems — the same guard
                # the terms note and the staleness warning carry.
                and not any(w.code == WarningCode.freshness_unavailable
                            and w.source_id == source_id
                            for w in self._warnings)):
            self.warn(WarningCode.freshness_unavailable,
                      "The publisher exposes no machine-readable update date "
                      "for this layer; retrieval time is known, data vintage "
                      "is not.", source_id)
        elif source_updated_at is not None and manifest is not None:
            self._warn_if_stale(source_id, manifest, source_updated_at,
                                retrieved_at)
        if terms_gap and not any(
                w.code == WarningCode.terms_note and w.source_id == source_id
                for w in self._warnings):
            self.warn(WarningCode.terms_note, terms_gap, source_id)
        return ref

    def _warn_if_stale(self, source_id: str, manifest,
                       source_updated_at: str, retrieved_at: str) -> None:
        """Say so when a publisher's data is older than its own promise.

        Measured against the cadence the manifest declares and nothing
        else (GitHub issue #57). A source that says `unknown` is not
        judged: there is no promise to be behind, and inventing a
        threshold would be this project deciding what "current" means
        for someone else's data.

        This is the other half of `freshness_unavailable`. That one says
        the vintage is unknown; this one says the vintage is known and
        older than the publisher led you to expect.
        """
        limit = manifest.freshness.stale_after_seconds()
        if limit is None:
            return
        age = _age_seconds(source_updated_at, retrieved_at)
        if age is None or age <= limit:
            return
        # Once per source, not once per layer. A tool that reads two
        # layers of one service adds the source entry twice, and the
        # same sentence twice reads as two separate problems. The terms
        # note guards itself the same way.
        if any(w.code == WarningCode.stale_source and w.source_id == source_id
               for w in self._warnings):
            return
        self.warn(
            WarningCode.stale_source,
            f"This data was last updated {age // 86_400} days before it "
            f"was retrieved, and {manifest.publisher.agency} describes "
            f"this source as updating {manifest.freshness.expected_cadence}. "
            "It is the publisher's own schedule that it is behind, not a "
            "deadline this project set. The records are still what the "
            "publisher holds; they may not be what it has most recently "
            "collected.", source_id)

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


def _age_seconds(source_updated_at: str, retrieved_at: str) -> int | None:
    """How far `source_updated_at` sits before `retrieved_at`.

    None when either timestamp is not the ISO shape every envelope uses,
    because a staleness claim computed from a string nobody could parse
    would be worse than no claim. A negative age — a publisher stamping
    data ahead of when it was read — reads as zero rather than as
    freshness from the future.
    """
    def parse(value: str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    updated, read = parse(source_updated_at), parse(retrieved_at)
    if updated is None or read is None:
        return None
    return max(0, int((read - updated).total_seconds()))


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


@dataclass
class Frame:
    """Resolved jurisdiction stack, or the envelope that ends the call."""

    stack: list[str] | None = None
    early: Envelope | None = None


def resolve_frame(jurisdictions, b: EnvelopeBuilder,
                  jurisdiction: str) -> Frame:
    resolution = jurisdictions.resolve(jurisdiction)
    if resolution.resolved is not None:
        j = resolution.resolved
        stack = [j.id] + [p.id for p in jurisdictions.parents_of(j)]
        if resolution.matched_former_name:
            # Every geo tool's description tells the caller to pass the
            # jurisdiction string as given, so a historical name reaches
            # here as readily as it reaches registry.resolve_jurisdiction
            # — and answering it silently returns current data under a
            # government that no longer exists.
            b.warn(WarningCode.alias_match,
                   f"{resolution.matched_former_name!r} names a Virginia "
                   "government that no longer exists under that name. "
                   f"This answer is about {j.name}, which governs that "
                   "territory now. A record using the old name predates "
                   "the change; check its date before treating this as "
                   "current.")
        return Frame(stack=stack)
    if resolution.candidates:
        env = b.build(
            {"resolved": None,
             "candidates": [c.model_dump() for c in resolution.candidates],
             "note": "The jurisdiction is ambiguous. Present these "
                     "candidates to the user; do not select one yourself."},
            Coverage(registry=RegistryCoverage.covered,
                     execution=ExecutionCoverage.complete,
                     pagination=PaginationCoverage.complete,
                     result=ResultCoverage.hit),
            requires_user_choice=True)
        return Frame(early=env)
    env = b.build(
        {"results": [],
         "note": f"{jurisdiction!r} matches no Virginia jurisdiction in the "
                 "table. registry.resolve_jurisdiction shows what resolves."},
        Coverage(registry=RegistryCoverage.covered,
                 execution=ExecutionCoverage.complete,
                 pagination=PaginationCoverage.complete,
                 result=ResultCoverage.empty))
    return Frame(early=env)
