"""Jurisdiction model and exact resolver (design/jurisdiction-resolution.md).

Spike scope: exact lookup by id / FIPS / name / alias. Point-in-polygon and
address geocoding arrive with the geo-vertical milestone; nothing here guesses.
Ambiguity is a first-class result: `resolve` returns candidates and never
picks (../../../design/architecture.md decision 0004).

The jurisdiction table is data (sources/jurisdictions/*.yaml), versioned and
reviewed like source manifests. FIPS codes in the seed set were verified
against Census TIGERweb on 2026-08-27.
"""
from __future__ import annotations

import enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class JurisdictionKind(str, enum.Enum):
    state = "state"
    county = "county"
    independent_city = "independent-city"
    town = "town"
    school_division = "school-division"
    regional_body = "regional-body"
    authority = "authority"
    special_district = "special-district"


class Jurisdiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: JurisdictionKind
    fips: str | None = None
    place_fips: str | None = None
    parent: str | None = None
    # Other jurisdictions whose territory this one also lies in. Twenty of
    # Virginia's incorporated towns straddle a county line — Herndon is in
    # Fairfax and Loudoun, Farmville in Prince Edward and Cumberland — and
    # `parent` can name only one of them. Deriving the parent from a single
    # interior point silently lost the rest.
    #
    # These reach `layered_authorities` and NOT the source-selection
    # stack, deliberately. A name alone cannot say which part of a
    # straddling town is meant, so querying the second county's sources
    # for "Herndon" would add records from ground the caller may not have
    # asked about. A coordinate does say, and point resolution already
    # returns the county that actually contains it.
    also_within: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    not_to_be_confused_with: list[str] = Field(default_factory=list)
    # Names of a government that no longer exists, whose territory this row
    # now governs. Three Virginia cities reverted to towns inside their
    # surrounding county (South Boston 1995, Clifton Forge 2001, Bedford
    # 2013), so records written before the reversion name a city that is
    # not in any current list. Resolving those to the successor is more
    # useful than "no match", and it is a different basis from an alias:
    # an alias is another way to say the same government's name, a former
    # name is a government that stopped existing. The resolver says which.
    former_names: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: JurisdictionKind
    distinguisher: str


class Resolution(BaseModel):
    """Either `resolved` is set (with basis) or `candidates` is non-empty."""

    model_config = ConfigDict(extra="forbid")

    resolved: Jurisdiction | None = None
    # exact_id | exact_fips | exact_name | alias | former_name
    basis: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    layered_authorities: list[dict[str, str]] = Field(default_factory=list)
    # Set only on a former_name match: the name the caller used, so the
    # tool can say which dead government's name it just translated.
    matched_former_name: str | None = None


class JurisdictionTable:
    def __init__(self, jurisdictions: list[Jurisdiction]) -> None:
        self._all = jurisdictions
        self._by_id = {j.id: j for j in jurisdictions}
        if len(self._by_id) != len(jurisdictions):
            seen: set[str] = set()
            dupes = [j.id for j in jurisdictions if j.id in seen or seen.add(j.id)]
            raise ValueError(f"duplicate jurisdiction ids: {dupes}")

    @classmethod
    def load(cls, directory: Path) -> "JurisdictionTable":
        files = sorted(directory.glob("*.yaml"))
        if not files:
            raise FileNotFoundError(
                f"no jurisdiction YAML found in {directory}; the table is "
                "load-bearing and an empty load must fail, not degrade")
        rows = [Jurisdiction.model_validate(yaml.safe_load(f.read_text()))
                for f in files]
        return cls(rows)

    def __len__(self) -> int:
        return len(self._all)

    def ids(self) -> set[str]:
        return set(self._by_id)

    def get(self, jur_id: str) -> Jurisdiction | None:
        return self._by_id.get(jur_id)

    def by_fips(self, fips: str) -> Jurisdiction | None:
        """Exact 5-digit county/independent-city FIPS. Returns None when the
        code is real but simply not in this table yet — the pilot table is a
        seed, not the Commonwealth's full 133 localities, and a caller must
        be able to tell 'not in our table' from 'no such place'."""
        hits = [j for j in self._all if j.fips == fips]
        return hits[0] if len(hits) == 1 else None

    def by_place_fips(self, place_fips: str) -> Jurisdiction | None:
        """Exact 5-digit place FIPS (towns), state prefix already stripped."""
        hits = [j for j in self._all if j.place_fips == place_fips]
        return hits[0] if len(hits) == 1 else None

    def parents_of(self, jur: Jurisdiction) -> list[Jurisdiction]:
        chain: list[Jurisdiction] = []
        cur = jur
        while cur.parent:
            parent = self._by_id.get(cur.parent)
            if parent is None:
                raise ValueError(
                    f"{cur.id} names parent {cur.parent!r} that is not in the "
                    "table — the table is inconsistent, fix the data")
            chain.append(parent)
            cur = parent
        return chain

    def _distinguisher(self, j: Jurisdiction) -> str:
        if j.kind == JurisdictionKind.independent_city:
            return "independent city, not a county"
        if j.kind == JurisdictionKind.county:
            return "county"
        if j.kind == JurisdictionKind.town and j.parent:
            return f"incorporated town inside {j.parent}"
        return j.kind.value

    def resolve(self, query: str) -> Resolution:
        """Exact resolution. `query` may be a va: id, a 5-digit FIPS, or a
        name/alias. Multiple name hits return candidates, never a pick."""
        q = query.strip()
        if not q:
            from .errors import InvalidQuery
            raise InvalidQuery("jurisdiction query is empty; pass a name, "
                               "FIPS code, or va: id")

        if q in self._by_id:
            return self._finish(self._by_id[q], "exact_id")

        if q.isdigit() and len(q) in (3, 5):
            fips = q if len(q) == 5 else f"51{q}"
            hits = [j for j in self._all if j.fips == fips]
            if len(hits) == 1:
                return self._finish(hits[0], "exact_fips")

        low = q.lower()
        exact = [j for j in self._all if j.name.lower() == low]
        alias = [j for j in self._all
                 if any(a.lower() == low for a in j.aliases)]
        # A former name is checked only when nothing current matches. A
        # live government always outranks a dead one with the same name;
        # otherwise "Bedford City" could shadow a real city if Virginia
        # ever chartered one again.
        former = [j for j in self._all
                  if any(f.lower() == low for f in j.former_names)]
        # A bare shared token ("fairfax", "richmond") matches the name minus
        # its kind suffix; these are the trap cases and must return candidates.
        stem = [j for j in self._all
                if low in (j.name.lower().removesuffix(" county"),
                           j.name.lower().removesuffix(" city"),
                           j.name.lower().removesuffix(" (town)"))]
        merged: dict[str, tuple[Jurisdiction, str]] = {}
        for j in exact:
            merged.setdefault(j.id, (j, "exact_name"))
        for j in alias:
            merged.setdefault(j.id, (j, "alias"))
        for j in stem:
            merged.setdefault(j.id, (j, "stem"))

        if len(merged) == 1:
            j, basis = next(iter(merged.values()))
            return self._finish(j, "exact_name" if basis == "stem" else basis)
        if len(merged) > 1:
            cands = [Candidate(id=j.id, name=j.name, kind=j.kind,
                               distinguisher=self._distinguisher(j))
                     for j, _ in sorted(merged.values(), key=lambda t: t[0].id)]
            return Resolution(candidates=cands)
        if len(former) == 1:
            return self._finish(former[0], "former_name",
                                matched_former_name=q)
        if len(former) > 1:
            cands = [Candidate(id=j.id, name=j.name, kind=j.kind,
                               distinguisher=self._distinguisher(j))
                     for j in sorted(former, key=lambda j: j.id)]
            return Resolution(candidates=cands)
        return Resolution()

    def _finish(self, j: Jurisdiction, basis: str,
                matched_former_name: str | None = None) -> Resolution:
        layered = [{"id": p.id, "relationship": "parent-" + p.kind.value}
                   for p in self.parents_of(j)]
        seen = {row["id"] for row in layered}
        for other_id in j.also_within:
            other = self._by_id.get(other_id)
            if other is not None and other.id not in seen:
                layered.append({"id": other.id,
                                "relationship": "also-within-" +
                                                other.kind.value})
                seen.add(other.id)
        for other_id in j.not_to_be_confused_with:
            other = self._by_id.get(other_id)
            # A place already in the stack as a parent needs no second row
            # saying not to confuse it with its own child: Bedford town
            # listing Bedford County twice, once as its county and once as
            # a confusable, reads as a bug rather than as two facts.
            if other is not None and other.id not in seen:
                layered.append({"id": other.id,
                                "relationship": "not-to-be-confused-with"})
                seen.add(other.id)
        return Resolution(resolved=j, basis=basis,
                          layered_authorities=layered,
                          matched_former_name=matched_former_name)
