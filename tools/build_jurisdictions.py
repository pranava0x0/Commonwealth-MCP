#!/usr/bin/env python3
"""Generate the jurisdiction table for every Virginia locality (issue #25).

Two independent sources seed it and check each other:

- VGIN's Administrative Boundaries localities layer, already registered
  here, which carries all 133 with FIPS, GNIS, and the publisher's own
  jurisdiction type.
- Census TIGERweb, the federal list, which carries FIPS and the legal name.

Neither is trusted alone. Where they disagree the row is still written and
the disagreement is reported for a human to look at, because a disagreement
between two official lists is a finding, not a merge conflict to resolve
silently.

The output is reviewed before it is committed:

    python tools/build_jurisdictions.py --report        # differences only
    python tools/build_jurisdictions.py --write         # write the YAML

Hand-written rows already on disk are preserved. A row's aliases,
`not_to_be_confused_with`, and any parent link are editorial judgments; the
generator supplies identity (id, name, kind, FIPS) and never overwrites
them. `--force` re-derives identity fields too, and prints what it changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JURISDICTIONS = ROOT / "sources" / "jurisdictions"

VGIN_LOCALITIES = ("https://vginmaps.vdem.virginia.gov/arcgis/rest/services/"
                   "VA_Base_Layers/VA_Admin_Boundaries/FeatureServer/1/query")
VGIN_TOWNS = ("https://vginmaps.vdem.virginia.gov/arcgis/rest/services/"
              "VA_Base_Layers/VA_Admin_Boundaries/FeatureServer/0/query")
# TIGERweb's current county layer. Virginia's independent cities are
# county-equivalents and live in this layer alongside its counties, which is
# the same shape VGIN uses and the reason the two are comparable at all.
TIGERWEB_COUNTIES = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
                     "TIGERweb/State_County/MapServer/1/query")

STATE_FIPS = "51"
TIMEOUT = 90


def fetch(url: str, params: dict[str, str]) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full, timeout=TIMEOUT) as resp:
        payload = json.loads(resp.read())
    if "error" in payload:
        raise SystemExit(f"upstream error from {url}: {payload['error']}")
    return payload


def vgin_localities() -> dict[str, dict]:
    """{fips: {name, full_name, type, gnis}} from the registered source."""
    payload = fetch(VGIN_LOCALITIES, {
        "f": "json", "where": "1=1", "returnGeometry": "false",
        "outFields": "STCOFIPS,NAME,NAMELSAD,JURISTYPE,GNIS",
        "resultRecordCount": "500"})
    out: dict[str, dict] = {}
    for feat in payload["features"]:
        a = feat["attributes"]
        fips = str(a["STCOFIPS"])
        # Prince George ships as two polygons under one FIPS
        # (design/source-quirks.md). One row per government, so the second
        # polygon is not a second jurisdiction.
        out.setdefault(fips, {"fips": fips, "name": a["NAME"],
                              "full_name": a["NAMELSAD"],
                              "type": a["JURISTYPE"], "gnis": a.get("GNIS")})
    return out


def vgin_towns() -> dict[str, dict]:
    payload = fetch(VGIN_TOWNS, {
        "f": "json", "where": "1=1", "returnGeometry": "false",
        "outFields": "STPLFIPS,NAME,NAMELSAD,GNIS",
        "resultRecordCount": "500"})
    out: dict[str, dict] = {}
    for feat in payload["features"]:
        a = feat["attributes"]
        raw = str(a["STPLFIPS"] or "")
        if not raw:
            continue
        bare = raw[len(STATE_FIPS):] if raw.startswith(STATE_FIPS) else raw
        out.setdefault(bare, {"place_fips": bare, "name": a["NAME"],
                              "full_name": a["NAMELSAD"],
                              "gnis": a.get("GNIS")})
    return out


def tigerweb_localities() -> dict[str, dict]:
    payload = fetch(TIGERWEB_COUNTIES, {
        "f": "json", "where": f"STATE='{STATE_FIPS}'",
        "returnGeometry": "false", "outFields": "GEOID,NAME,BASENAME",
        "resultRecordCount": "500"})
    return {str(f["attributes"]["GEOID"]): {
        "fips": str(f["attributes"]["GEOID"]),
        "name": f["attributes"]["NAME"],
        "basename": f["attributes"]["BASENAME"]}
        for f in payload["features"]}


# VGIN's own JURISTYPE values, mapped to the project's JurisdictionKind.
# Anything outside this table stops the run rather than being guessed at:
# a new value means the publisher changed something worth reading.
JURISTYPE_KIND = {"CO": "county", "CI": "independent-city"}


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode(
        "ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def row_id(name: str, kind: str) -> str:
    """`va:fairfax-county` / `va:fairfax-city` — the kind suffix is what
    keeps the two Fairfaxes distinguishable in an id, and the resolver's
    stem matching depends on it."""
    slug = slugify(name)
    suffix = "county" if kind == "county" else "city"
    return f"va:{slug}-{suffix}" if not slug.endswith(f"-{suffix}") \
        else f"va:{slug}"


def derive_rows(vgin: dict[str, dict], tiger: dict[str, dict],
                ) -> tuple[list[dict], list[str]]:
    """(rows, differences). Every FIPS in either list produces a row."""
    differences: list[str] = []
    only_vgin = sorted(set(vgin) - set(tiger))
    only_tiger = sorted(set(tiger) - set(vgin))
    for fips in only_vgin:
        differences.append(
            f"{fips}: in VGIN ({vgin[fips]['full_name']}) and not TIGERweb")
    for fips in only_tiger:
        differences.append(
            f"{fips}: in TIGERweb ({tiger[fips]['name']}) and not VGIN")

    rows = []
    for fips in sorted(set(vgin) | set(tiger)):
        v, t = vgin.get(fips), tiger.get(fips)
        if v is not None:
            juristype = v["type"]
            if juristype not in JURISTYPE_KIND:
                raise SystemExit(
                    f"{fips}: unrecognised VGIN JURISTYPE {juristype!r}. "
                    "The publisher's vocabulary changed; read it before "
                    "mapping it.")
            kind = JURISTYPE_KIND[juristype]
            name = v["full_name"]
        else:
            # TIGERweb-only: its NAME already reads "X County" / "X city".
            name = t["name"]
            kind = "county" if name.lower().endswith(" county") \
                else "independent-city"
        if v is not None and t is not None:
            # TIGERweb spells independent cities lowercase ("Fairfax city");
            # compare case-insensitively so a spelling convention is not
            # reported as a disagreement about which place this is.
            if v["full_name"].lower() != t["name"].lower():
                differences.append(
                    f"{fips}: VGIN says {v['full_name']!r}, TIGERweb says "
                    f"{t['name']!r}")
        # Every locality sits under the Commonwealth. Without the link,
        # `parents_of()` returns an empty chain and the state never appears
        # in layered_authorities — a county that answers to nobody.
        rows.append({"id": row_id(name, kind), "name": name, "kind": kind,
                     "fips": fips, "parent": "va"})
    return rows, differences


TIGERWEB_PLACES = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
                   "TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4/query")


def tigerweb_place_points() -> dict[str, tuple[float, float]]:
    """{place_fips: (lon, lat)} from TIGERweb's internal points.

    An internal point is not a centroid: Census guarantees it lies INSIDE
    the polygon, which a centre of mass does not (the same donut problem
    that makes a county centroid land in the independent city it encloses —
    docs/audits/centroid-property-2026-08-28.json). Using the guaranteed
    interior point is what makes a single containment test correct."""
    payload = fetch(TIGERWEB_PLACES, {
        "f": "json", "where": f"STATE='{STATE_FIPS}'",
        "returnGeometry": "false", "outFields": "PLACE,INTPTLON,INTPTLAT",
        "resultRecordCount": "1000"})
    out = {}
    for feat in payload["features"]:
        a = feat["attributes"]
        try:
            out[str(a["PLACE"])] = (float(a["INTPTLON"]),
                                    float(a["INTPTLAT"]))
        except (TypeError, ValueError):
            continue
    return out


def locality_polygons() -> list[tuple[str, list]]:
    """[(fips, rings)] for every county and independent city, fetched once.

    One request instead of one containment query per town: 191 live point
    queries against a government service to answer a question that is
    arithmetic once the polygons are in hand is not a politeness budget
    well spent."""
    payload = fetch(VGIN_LOCALITIES, {
        "f": "json", "where": "1=1", "returnGeometry": "true",
        "outFields": "STCOFIPS", "outSR": "4326",
        # Same generalization the boundary tool uses (~22 m). A town's
        # interior point sits well away from its county's edge, so this
        # is comfortably inside the tolerance; the run reports any town
        # that lands in zero or several counties rather than picking.
        "maxAllowableOffset": "0.0002",
        "resultRecordCount": "500"})
    return [(str(f["attributes"]["STCOFIPS"]),
             (f.get("geometry") or {}).get("rings") or [])
            for f in payload["features"]]


def point_in_rings(lon: float, lat: float, rings: list) -> bool:
    """Even-odd ray casting over an esriPolygon's rings.

    Esri orders outer rings clockwise and holes counter-clockwise, and
    even-odd handles holes without needing to know which is which: a point
    inside an outer ring and inside a hole crosses both and comes out
    even."""
    inside = False
    for ring in rings:
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i + 1][0], ring[i + 1][1]
            if (y1 > lat) != (y2 > lat):
                x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if lon < x_at:
                    inside = not inside
    return inside


def intersecting_localities(place_fips: str) -> list[str]:
    """Locality FIPS codes whose polygon intersects one town's polygon,
    asked of VGIN directly. The fallback for a town Census no longer
    carries as an incorporated place."""
    town = fetch(VGIN_TOWNS, {
        "f": "json", "where": f"STPLFIPS = '{STATE_FIPS}{place_fips}'",
        "returnGeometry": "true", "outFields": "STPLFIPS", "outSR": "4326",
        "resultRecordCount": "5"})
    features = town.get("features") or []
    if not features:
        return []
    geometry = dict(features[0].get("geometry") or {})
    geometry.setdefault("spatialReference", {"wkid": 4326})
    hit = fetch(VGIN_LOCALITIES, {
        "f": "json", "geometry": json.dumps(geometry),
        "geometryType": "esriGeometryPolygon", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "false",
        "outFields": "STCOFIPS", "resultRecordCount": "10"})
    return sorted({str(f["attributes"]["STCOFIPS"])
                   for f in hit.get("features") or []})


def town_rows(towns: dict[str, dict], localities: list[dict],
              ) -> tuple[list[dict], list[str]]:
    """Towns get a `place_fips` and a `parent`.

    The towns layer carries no county code, so the parent has to be
    derived. Without one, a town resolves with an empty parent chain and
    the layered-authority answer ("the town AND its county govern here")
    silently becomes "just the town" — worse than not being in the table
    at all, where the resolver at least says `unmapped_match` and names
    the place."""
    by_fips = {row["fips"]: row["id"] for row in localities
               if row.get("fips")}
    points = tigerweb_place_points()
    polygons = locality_polygons()
    rows, notes = [], []
    for place_fips, t in sorted(towns.items()):
        row = {"id": f"va:{slugify(t['name'])}-town",
               "name": f"{t['name']} (town)", "kind": "town",
               "place_fips": place_fips}
        point = points.get(place_fips)
        if point is not None:
            basis = "TIGERweb interior point"
            containing = sorted({fips for fips, rings in polygons
                                 if point_in_rings(point[0], point[1], rings)})
        else:
            # VGIN publishes a polygon for a place TIGERweb's current
            # Incorporated Places layer does not. Rather than dropping the
            # parent, ask the same publisher: which locality polygons does
            # this town's own polygon intersect? That is one extra request
            # per case (two in the 2026-08-29 run) and needs no interior-
            # point assumption at all.
            basis = ("not in TIGERweb's Incorporated Places; VGIN polygon "
                     "intersection instead")
            containing = intersecting_localities(place_fips)
            notes.append(f"town {place_fips} ({t['name']}): {basis}")
        parents = [by_fips[f] for f in containing if f in by_fips]
        if len(parents) == 1:
            row["parent"] = parents[0]
        elif not parents:
            notes.append(f"town {place_fips} ({t['name']}): {basis} matched "
                         "no locality polygon; parent not derived")
        else:
            # A town on a county line intersects both. Which county
            # governs it is a legal fact, not a geometric one, so the
            # generator declines and a human writes the parent in.
            notes.append(f"town {place_fips} ({t['name']}): {basis} matched "
                         f"{len(parents)} localities "
                         f"({', '.join(parents)}); parent not derived")
        rows.append(row)
    return rows, notes


def load_existing() -> dict[str, tuple[Path, dict]]:
    import yaml
    out = {}
    for path in sorted(JURISDICTIONS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        out[doc["id"]] = (path, doc)
    return out


IDENTITY = ("name", "kind", "fips", "place_fips")
EDITORIAL_LISTS = ("aliases", "not_to_be_confused_with", "former_names")
EDITORIAL = ("parent",) + EDITORIAL_LISTS


def leading_comment(path: Path) -> str:
    """A hand-written row's header comment is the only place some findings
    live (Prince George's two-polygon quirk, for one). Regenerating the
    file must not delete it."""
    if not path.exists():
        return ""
    kept = []
    for line in path.read_text().splitlines():
        if not line.startswith("#"):
            break
        kept.append(line)
    return "\n".join(kept) + "\n" if kept else ""


def render(doc: dict, header: str = "") -> str:
    """Hand-shaped YAML rather than yaml.dump: these files are read and
    edited by people, and the key order is the order a reader wants."""
    lines = [f"id: {doc['id']}", f"name: {doc['name']}",
             f"kind: {doc['kind']}"]
    for key in ("fips", "place_fips"):
        if doc.get(key):
            lines.append(f'{key}: "{doc[key]}"')
    if doc.get("parent"):
        lines.append(f"parent: {doc['parent']}")
    # Every list field a row may carry. Omitting one here does not fail
    # loudly, it silently deletes that field on the next --write: this
    # dropped `former_names` off the three reverted-city rows, which
    # reopens design/jurisdiction-resolution.md § 3's Bedford trap without
    # touching a test.
    for key in EDITORIAL_LISTS:
        if doc.get(key):
            items = ", ".join(json.dumps(a) for a in doc[key])
            lines.append(f"{key}: [{items}]")
    return header + "\n".join(lines) + "\n"


def default_aliases(doc: dict) -> list[str]:
    """The two forms a person actually types. `Fairfax County` resolves on
    its name already; `County of Fairfax` and the bare stem do not, and the
    bare stem is deliberately NOT added — it is what makes a name ambiguous
    between the county and the city, and the resolver returns candidates
    for it by design."""
    name, kind = doc["name"], doc["kind"]
    if kind == "county":
        base = name.removesuffix(" County")
        out = [f"County of {base}"]
    elif kind == "independent-city":
        base = re.sub(r"\s+city$", "", name, flags=re.IGNORECASE)
        out = [f"City of {base}", f"{base} City"]
    elif kind == "town":
        out = [f"Town of {name.removesuffix(' (town)')}"]
    else:
        return []
    # An alias identical to the name adds a second way to spell the same
    # string and no new way to find the place.
    return [a for a in out if a.lower() != name.lower()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true",
                    help="print source differences and the planned diff")
    ap.add_argument("--write", action="store_true", help="write YAML rows")
    ap.add_argument("--force", action="store_true",
                    help="also re-derive identity fields on existing rows")
    ap.add_argument("--towns", action="store_true",
                    help="include incorporated towns, with parents derived "
                         "by containment against the locality polygons")
    args = ap.parse_args()
    if not (args.report or args.write):
        ap.error("pass --report or --write")

    vgin = vgin_localities()
    tiger = tigerweb_localities()
    towns = vgin_towns()
    print(f"VGIN localities: {len(vgin)}   TIGERweb: {len(tiger)}   "
          f"VGIN towns: {len(towns)}", file=sys.stderr)

    rows, differences = derive_rows(vgin, tiger)
    if args.towns:
        towns_out, town_notes = town_rows(towns, rows)
        rows += towns_out
        differences += town_notes
    existing = load_existing()

    print(f"\n{len(differences)} difference(s) and unresolved case(s):")
    for d in differences:
        print(f"  {d}")

    added, changed, kept = [], [], []
    planned: dict[str, dict] = {}
    for row in rows:
        if row["id"] in existing:
            _, doc = existing[row["id"]]
            merged = dict(doc)
            if args.force:
                deltas = [f"{k}: {doc.get(k)!r} -> {row[k]!r}"
                          for k in IDENTITY
                          if k in row and doc.get(k) != row[k]]
                if deltas:
                    changed.append(f"{row['id']}: " + "; ".join(deltas))
                    merged.update({k: v for k, v in row.items()
                                   if k in IDENTITY})
            else:
                kept.append(row["id"])
            planned[row["id"]] = merged
        else:
            new = dict(row)
            aliases = default_aliases(new)
            if aliases:
                new["aliases"] = aliases
            added.append(row["id"])
            planned[row["id"]] = new

    orphans = sorted(set(existing) - set(planned))
    print(f"\n{len(added)} new row(s), {len(changed)} changed, "
          f"{len(kept)} left as written, {len(orphans)} on disk with no "
          f"upstream match")
    for o in orphans:
        print(f"  no upstream match (kept): {o}")
    for c in changed:
        print(f"  changed: {c}")

    if not args.write:
        for a in added[:10]:
            print(f"  would add: {a}")
        if len(added) > 10:
            print(f"  ... and {len(added) - 10} more")
        return 0

    written = 0
    for jid, doc in planned.items():
        path = existing[jid][0] if jid in existing else \
            JURISDICTIONS / (jid.removeprefix("va:") + ".yaml")
        text = render(doc, leading_comment(path))
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            written += 1
    print(f"wrote {written} file(s) into {JURISDICTIONS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
