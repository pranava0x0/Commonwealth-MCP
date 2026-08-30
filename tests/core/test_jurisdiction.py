"""The named traps from design/jurisdiction-resolution.md § 3 (exact-lookup
subset — geometry cases arrive with the geo-vertical milestone)."""
import pytest

from commonwealth.core.jurisdiction import (Jurisdiction, JurisdictionKind,
                                            JurisdictionTable)


@pytest.fixture(scope="module")
def table() -> JurisdictionTable:
    from commonwealth.runtime import SOURCES_DIR
    return JurisdictionTable.load(SOURCES_DIR / "jurisdictions")


def test_table_covers_every_virginia_locality(table):
    """133 counties and independent cities, 191 incorporated towns, plus
    the state itself (issue #25). The counts come from the two lists the
    generator cross-checked — VGIN's boundary layer and Census TIGERweb
    agreed on all 133 on 2026-08-29 — so a drop here means rows were lost,
    not that Virginia reorganised."""
    kinds: dict[str, int] = {}
    for jid in sorted(table.ids()):
        kinds[table.get(jid).kind.value] = kinds.get(
            table.get(jid).kind.value, 0) + 1
    assert kinds["county"] == 95
    assert kinds["independent-city"] == 38
    assert kinds["town"] == 191
    assert kinds["state"] == 1
    assert len(table) == 325


def test_every_locality_sits_under_the_state(table):
    """A row with no parent chain reports no layered authorities, so a
    county would answer to nobody. Only the state itself has no parent."""
    orphans = [jid for jid in sorted(table.ids())
               if jid != "va" and not table.get(jid).parent]
    assert orphans == [], orphans


def test_every_parent_link_resolves(table):
    """`parents_of` raises on a dangling parent, so walking every row is
    the check. 190 of the town parents were derived by containment and one
    was written by hand; a typo in any of them fails here."""
    for jid in sorted(table.ids()):
        table.parents_of(table.get(jid))


def test_no_stale_bedford_city_row_exists(table):
    """§ 3 trap 8. Bedford reverted from city to town in 2013; a
    va:bedford-city row would be a government that does not exist."""
    assert table.get("va:bedford-city") is None
    assert "va:bedford-city" not in table.ids()


def test_a_former_city_name_resolves_to_its_successor_and_says_so(table):
    """§ 3 trap 8's other half: a record naming the dissolved city must
    not come back as 'no such place', and must not come back looking
    current either."""
    for old, now in (("Bedford City", "va:bedford-town"),
                     ("Clifton Forge City", "va:clifton-forge-town"),
                     ("City of South Boston", "va:south-boston-town")):
        r = table.resolve(old)
        assert r.resolved is not None and r.resolved.id == now, old
        assert r.basis == "former_name", old
        assert r.matched_former_name == old, old


def test_a_current_name_always_beats_a_former_one(table):
    """Former names are consulted only when nothing current matches, so a
    live government can never be shadowed by a dead one's name."""
    r = table.resolve("Bedford County")
    assert r.resolved.id == "va:bedford-county" and r.basis == "exact_name"
    assert r.matched_former_name is None


def test_bedford_alone_is_ambiguous_between_the_county_and_the_town(table):
    r = table.resolve("bedford")
    assert r.resolved is None
    assert [c.id for c in r.candidates] == ["va:bedford-county",
                                            "va:bedford-town"]


def test_a_parent_is_not_repeated_as_a_confusable(table):
    """Bedford town names its own county in not_to_be_confused_with, which
    is true and would otherwise print the same id twice in one stack."""
    r = table.resolve("Town of Bedford")
    ids = [a["id"] for a in r.layered_authorities]
    assert len(ids) == len(set(ids)), ids


def test_fairfax_is_ambiguous_and_never_picked(table):
    r = table.resolve("fairfax")
    assert r.resolved is None
    ids = [c.id for c in r.candidates]
    assert ids == ["va:fairfax-city", "va:fairfax-county"]
    d = {c.id: c.distinguisher for c in r.candidates}
    assert "independent city" in d["va:fairfax-city"]


def test_richmond_and_roanoke_and_franklin_pairs_are_ambiguous(table):
    for name in ("richmond", "roanoke", "franklin"):
        r = table.resolve(name)
        assert r.resolved is None and len(r.candidates) == 2, name


def test_exact_full_names_resolve(table):
    assert table.resolve("Fairfax County").resolved.id == "va:fairfax-county"
    assert table.resolve("Richmond City").resolved.id == "va:richmond-city"


def test_fips_resolves(table):
    r = table.resolve("51059")
    assert r.resolved.id == "va:fairfax-county" and r.basis == "exact_fips"
    assert table.resolve("51600").resolved.id == "va:fairfax-city"


def test_alias_resolves(table):
    assert table.resolve("City of Fairfax").resolved.id == "va:fairfax-city"


def test_charles_city_county_is_a_county_not_a_city(table):
    """§ 3.6. Two halves, and the second is the actual trap: Charles City
    County is a county, AND there is no Charles City to be confused with,
    so no `not-to-be-confused-with` row may appear. Seeding one would
    invent a government."""
    r = table.resolve("Charles City County")
    assert r.resolved.kind == JurisdictionKind.county
    assert not [x for x in r.layered_authorities
                if x["relationship"] == "not-to-be-confused-with"]


def test_vienna_carries_parent_stack_and_id(table):
    r = table.resolve("Vienna")
    assert r.resolved.id == "va:vienna-town"
    parent_ids = [x["id"] for x in r.layered_authorities
                  if x["relationship"].startswith("parent")]
    assert parent_ids == ["va:fairfax-county", "va"]


def test_not_to_be_confused_with_surfaces(table):
    r = table.resolve("Fairfax County")
    rels = {(x["id"], x["relationship"]) for x in r.layered_authorities}
    assert ("va:fairfax-city", "not-to-be-confused-with") in rels


def test_unknown_name_is_empty_not_error(table):
    r = table.resolve("Atlantis")
    assert r.resolved is None and r.candidates == []


def test_empty_query_raises_invalid_query(table):
    from commonwealth.core.errors import InvalidQuery as IQ
    with pytest.raises(IQ):
        table.resolve("   ")


def test_duplicate_ids_refuse_to_load():
    j = Jurisdiction(id="va:x", name="X", kind=JurisdictionKind.county)
    with pytest.raises(ValueError, match="duplicate"):
        JurisdictionTable([j, j])


def test_missing_parent_fails_loud(table):
    j = Jurisdiction(id="va:orphan", name="Orphan", kind=JurisdictionKind.town,
                     parent="va:nowhere")
    t = JurisdictionTable([j])
    with pytest.raises(ValueError, match="not in the table"):
        t.parents_of(j)
