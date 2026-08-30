"""Regressions for the four findings in PR #38's first review round.

Each is pinned where it was possible to reproduce it, and by the shape of
the bug rather than by the specific value that exposed it — three of the
four were silent in a green suite.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from commonwealth.domains.geo import find_address, find_buildings
from commonwealth.runtime import PROJECT_ROOT, SOURCES_DIR

JURISDICTIONS = SOURCES_DIR / "jurisdictions"


async def test_a_point_address_query_is_scoped_to_the_jurisdiction(cw_ctx,
                                                                   monkeypatch):
    """P1. The buffer reaches 100 m, so a point near a locality line pulls
    in the neighbour's address points — and the envelope reports
    `jurisdictions_searched: [the one you asked for]`, so a caller reads
    them as local. The string path was scoped and the point path was not.

    Asserted on the query the adapter actually receives, because the
    recorded response looks the same either way."""
    seen: list[dict] = []
    real = cw_ctx.arcgis.query

    async def spy(manifest, layer_key, **kwargs):
        if layer_key == "addresses":
            seen.append(kwargs)
        return await real(manifest, layer_key, **kwargs)

    monkeypatch.setattr(cw_ctx.arcgis, "query", spy)
    await find_address(cw_ctx, jurisdiction="Vienna",
                       lon=-77.26436153964, lat=38.90067620715)
    assert seen, "no address query was issued"
    assert seen[0]["where_equals"] == {"fips": "51059"}, seen[0]


async def test_the_string_path_stays_scoped_too(cw_ctx, monkeypatch):
    """The fix moved the scoping call; this holds the half that already
    worked, so a future refactor cannot trade one for the other."""
    seen: list[dict] = []
    real = cw_ctx.arcgis.query

    async def spy(manifest, layer_key, **kwargs):
        if layer_key == "addresses":
            seen.append(kwargs)
        return await real(manifest, layer_key, **kwargs)

    monkeypatch.setattr(cw_ctx.arcgis, "query", spy)
    await find_address(cw_ctx, jurisdiction="Fairfax County",
                       address="4501 Carlby Ln")
    assert seen[0]["where_equals"] == {"fips": "51059"}, seen[0]


async def test_a_parcel_based_building_answer_names_the_parcel_source(
        cw_ctx):
    """P2. The building facts rest on the parcel polygon that defined the
    intersection, and the parcel query was never registered — so with more
    than one parcel source selectable a caller could not tell which one
    drew the boundary. find_zoning already did this correctly."""
    env = await find_buildings(cw_ctx, jurisdiction="Richmond City",
                               pin="C0010126019")
    source_ids = {s.source_id for s in env.provenance}
    assert "va-vgin-building-footprints" in source_ids
    assert "va-richmond-city-parcels-zoning" in source_ids, (
        "the parcel source that determined the intersection is missing "
        "from provenance")
    block = env.data["results"][0]
    parcel_ref = block["parcel_evidence_ref"]
    assert parcel_ref in {e.id for e in env.evidence}
    for row in block["records"]:
        assert parcel_ref in row["evidence_refs"], row


def test_the_jurisdiction_generator_renders_every_list_field_it_reads():
    """P2, and the worst of the four: `render()` emitted `aliases` and
    `not_to_be_confused_with` and nothing else, so the next
    `--write` would silently delete `former_names` from the three
    reverted-city rows and reopen the Bedford trap without touching a
    test.

    Derived from the module's own constant rather than a hand-typed list,
    because a hand-typed list here is the bug."""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import build_jurisdictions as gen

    rendered = gen.render({"id": "va:x", "name": "X", "kind": "town",
                           **{k: ["v"] for k in gen.EDITORIAL_LISTS}})
    for key in gen.EDITORIAL_LISTS:
        assert f"{key}: " in rendered, (
            f"{key} is read from disk and never written back")
    # Every list field any committed row carries must be in that constant.
    on_disk = set()
    for path in JURISDICTIONS.glob("*.yaml"):
        doc = yaml.safe_load(path.read_text())
        on_disk |= {k for k, v in doc.items() if isinstance(v, list)}
    assert on_disk <= set(gen.EDITORIAL_LISTS), (
        f"rows carry list fields the generator would drop: "
        f"{sorted(on_disk - set(gen.EDITORIAL_LISTS))}")


def test_the_reverted_city_rows_survive_a_regeneration():
    """The same check against the real rows rather than a synthetic one,
    and without the network: render each from what is on disk and confirm
    the text round-trips byte for byte."""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import build_jurisdictions as gen

    for name in ("bedford-town", "clifton-forge-town", "south-boston-town"):
        path = JURISDICTIONS / f"{name}.yaml"
        doc = yaml.safe_load(path.read_text())
        assert doc["former_names"], name
        assert gen.render(doc, gen.leading_comment(path)) == path.read_text(), (
            f"{name}.yaml does not round-trip through the generator; a "
            "--write would rewrite it")


def test_the_geocoder_sample_command_calls_its_own_coroutine():
    """P2. A `str.replace` with no count rewrote two call sites that
    happened to share a line, so `_sample_geocoder` called a nested
    function defined in a different function. Checked by parsing rather
    than by running, because reproducing it needs the network."""
    tree = ast.parse((PROJECT_ROOT / "src" / "commonwealth" / "cli" /
                      "__main__.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_sample_geocoder")
    defined = {n.name for n in ast.walk(fn)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    import builtins
    module_level = {n.name for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef))}
    imported = {(a.asname or a.name).split(".")[0] for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}
    unresolved = (called - defined - module_level - imported
                  - set(dir(builtins)))
    assert unresolved == set(), (
        f"_sample_geocoder calls names it does not define: {unresolved}")


@pytest.mark.parametrize("source_id", ["va-vgin-composite-locator"])
def test_every_documented_sample_command_at_least_starts(source_id):
    """The command is documented in CONTRIBUTING and design/source-registry
    § 4, and this one raised NameError before reaching the network. The
    run is expected to fail without a network; a NameError is not."""
    proc = subprocess.run(
        [sys.executable, "-m", "commonwealth.cli", "sources", "sample",
         source_id],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=180)
    assert "NameError" not in proc.stderr, proc.stderr[-600:]
    assert "AttributeError" not in proc.stderr, proc.stderr[-600:]
