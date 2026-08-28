"""The named traps from design/jurisdiction-resolution.md § 3 (exact-lookup
subset — geometry cases arrive with the geo-vertical milestone)."""
import pytest

from commonwealth.core.jurisdiction import (Jurisdiction, JurisdictionKind,
                                            JurisdictionTable)


@pytest.fixture(scope="module")
def table() -> JurisdictionTable:
    from commonwealth.runtime import SOURCES_DIR
    return JurisdictionTable.load(SOURCES_DIR / "jurisdictions")


def test_table_loads_all_seed_rows(table):
    assert len(table) == 14, "seed set changed — update this count deliberately"


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
    r = table.resolve("Charles City County")
    assert r.resolved.kind == JurisdictionKind.county


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
