"""Replay the committed fixtures against the live services and record what moved.

The test suite replays recorded government responses, which is what makes
it fast and offline. The risk it takes on is that the recordings drift from
what the services actually return, and nothing notices until someone runs
live. `design/testing-and-demos.md` makes the sharper version of the point:
because the offline tests replay recordings, only a live replay can notice
that a recorded quirk has *stopped* reproducing.

Drift is the expected output, not a failure. Government services rename
fields, renumber layers, and change projections. The point is to find out
when that happened, rather than during someone else's query. This exits
nonzero only when it could not run at all.

    .venv/bin/python tools/upstream_audit.py            # every source
    .venv/bin/python tools/upstream_audit.py --source va-fairfax-parcels-zoning
    .venv/bin/python tools/upstream_audit.py --dry-run  # what it would check

Writes two things:

- `docs/audits/upstream-<date>.md`, for a person. Every source appears,
  whether or not it changed, because an empty diff and a skipped source
  have to be distinguishable.
- `docs/audits/probe-history.json`, for the next run. Successive feature
  counts accumulate here, which is what a health floor set from a range
  rather than from a single reading needs (GitHub issue #19).

Cadence: weekly, set in `.github/workflows/upstream-drift.yml`. No manifest
declares a probe cadence of its own; the fastest `freshness.expected_cadence`
among registered sources is daily, so weekly sits under every one of them.
The politeness budget applies to audits too.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from commonwealth.adapters import arcgis as arcgis_mod  # noqa: E402
from commonwealth.adapters.base import (HttpFetcher,  # noqa: E402
                                        egress_policy_for)
from commonwealth.core.errors import CommonwealthError  # noqa: E402
from commonwealth.core.registry import SourceManifest  # noqa: E402
from commonwealth.runtime import load_context  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sources"
AUDITS = ROOT / "docs" / "audits"
HISTORY = AUDITS / "probe-history.json"

# Adapter types with no endpoint to reach. Not probing them is the correct
# outcome rather than a gap, and the report says so rather than omitting
# them.
NO_ENDPOINT = {"inventory"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- structural comparison -------------------------------------------------

def _shape(payload: Any) -> dict:
    """What a recorded response is compared on.

    Structural rather than byte-level, per the issue this implements: a
    fresh `recorded_at` is not drift, and neither is a feature arriving in
    a different order. What matters is whether the fields, their types,
    the layer's identity, and the size of the answer still match.
    """
    if not isinstance(payload, dict):
        return {"kind": type(payload).__name__}

    out: dict[str, Any] = {}
    # A layer-info response.
    for key in ("id", "name", "type", "geometryType", "objectIdField"):
        if key in payload:
            out[key] = payload[key]
    if isinstance(payload.get("fields"), list):
        out["fields"] = {f.get("name"): f.get("type")
                         for f in payload["fields"]
                         if isinstance(f, dict)}

    # A query response.
    if "count" in payload:
        out["count"] = payload["count"]
    features = payload.get("features")
    if isinstance(features, list):
        out["feature_count"] = len(features)
        attrs: Counter = Counter()
        types: dict[str, str] = {}
        geometry = False
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = geometry or bool(feature.get("geometry"))
            for name, value in (feature.get("attributes") or {}).items():
                attrs[name] += 1
                types.setdefault(name, type(value).__name__)
        out["attribute_fields"] = sorted(attrs)
        out["attribute_types"] = types
        out["has_geometry"] = geometry
    if "error" in payload:
        out["error"] = (payload["error"] or {}).get("code")
    if "candidates" in payload:  # the geocoder
        out["candidate_count"] = len(payload.get("candidates") or [])
        out["spatialReference"] = payload.get("spatialReference")
    return out


def _diff(before: dict, after: dict) -> list[str]:
    """Human-readable differences between two shapes, most useful first."""
    notes: list[str] = []

    fields_before = before.get("fields") or before.get("attribute_types") or {}
    fields_after = after.get("fields") or after.get("attribute_types") or {}
    gone = sorted(set(fields_before) - set(fields_after))
    added = sorted(set(fields_after) - set(fields_before))
    retyped = sorted(name for name in set(fields_before) & set(fields_after)
                     if fields_before[name] != fields_after[name])
    if gone:
        notes.append(f"fields gone: {', '.join(gone)}")
    if added:
        notes.append(f"fields added: {', '.join(added)}")
    for name in retyped:
        notes.append(f"field {name} changed type: "
                     f"{fields_before[name]} -> {fields_after[name]}")

    for key, label in (("id", "layer id"), ("name", "layer name"),
                       ("geometryType", "geometry type"),
                       ("objectIdField", "object id field"),
                       ("error", "error code")):
        if before.get(key) != after.get(key):
            notes.append(f"{label}: {before.get(key)!r} -> {after.get(key)!r}")

    for key, label in (("count", "count"),
                       ("feature_count", "features returned"),
                       ("candidate_count", "geocoder candidates")):
        if key in before or key in after:
            old, new = before.get(key), after.get(key)
            if old != new:
                notes.append(f"{label}: {old} -> {new}")

    if before.get("has_geometry") != after.get("has_geometry"):
        notes.append(f"geometry present: {before.get('has_geometry')} -> "
                     f"{after.get('has_geometry')}")
    return notes


# --- replaying one source --------------------------------------------------

async def _replay(manifest: SourceManifest, recorded: dict) -> dict:
    """Send every recorded request again and compare the shapes."""
    exchanges = recorded.get("exchanges") or []
    if not exchanges:
        return {"status": "no_fixture", "checked": 0, "findings": []}

    service_url = manifest.adapter.model_dump().get("service_url")
    if not service_url:
        return {"status": "no_endpoint", "checked": 0, "findings": []}
    fetcher = HttpFetcher(policy=egress_policy_for(manifest, service_url))

    findings: list[dict] = []
    checked = 0
    unreachable = 0
    for exchange in exchanges:
        url, params = exchange["url"], exchange["params"]
        try:
            live = await fetcher.fetch_json(url, params)
        except CommonwealthError as err:
            unreachable += 1
            findings.append({"request": _label(url, params),
                             "notes": [f"request failed: {err.code}: {err}"]})
            continue
        checked += 1
        notes = _diff(_shape(exchange["response"]), _shape(live))
        if notes:
            findings.append({"request": _label(url, params), "notes": notes})

    status = "checked"
    if unreachable and not checked:
        status = "unreachable"
    elif unreachable:
        status = "partly_unreachable"
    return {"status": status, "checked": checked,
            "unreachable": unreachable, "findings": findings}


def _label(url: str, params: dict) -> str:
    """A short name for one recorded request, for the report."""
    tail = url.rsplit("/arcgis/rest/services/", 1)[-1]
    where = params.get("where") or params.get("SingleLine") or ""
    if params.get("returnCountOnly"):
        return f"{tail} (count)"
    return f"{tail}{' where ' + where if where else ''}"[:150]


async def _replay_pages(ctx, manifest: SourceManifest, sid: str) -> dict:
    """The HTML source, which records pages rather than JSON exchanges.

    Compared on what the parser actually reads — whether the section was
    found, its heading, and how many paragraphs came back — because a
    markup redesign breaks parsing before it breaks any published
    contract, and that is the drift worth catching here.
    """
    known = manifest.health.expect.get("known_section")
    absent = manifest.health.expect.get("absent_section", "1-99999999")
    findings: list[dict] = []
    checked = 0
    unreachable = 0
    for citation, should_exist in ((known, True), (absent, False)):
        if not citation:
            continue
        try:
            section = await ctx.virginia_law.get_section(manifest, citation)
        except CommonwealthError as err:
            unreachable += 1
            findings.append({"request": f"section {citation}",
                             "notes": [f"request failed: {err.code}: {err}"]})
            continue
        checked += 1
        found = section is not None
        if found is not should_exist:
            findings.append({
                "request": f"section {citation}",
                "notes": [f"expected {'a section' if should_exist else 'no section'}, "
                          f"got {'a section' if found else 'none'}"]})
        elif found and not section.paragraphs:
            findings.append({
                "request": f"section {citation}",
                "notes": ["the page was found and parsed to zero "
                          "paragraphs, which is what a markup redesign "
                          "looks like from here"]})
    status = "checked"
    if unreachable and not checked:
        status = "unreachable"
    elif unreachable:
        status = "partly_unreachable"
    return {"status": status, "checked": checked,
            "unreachable": unreachable, "findings": findings}


async def _probe(ctx, manifest: SourceManifest) -> list[dict]:
    """Live feature counts per layer, with the manifest's floor alongside.

    These readings are the input #19 needs: a floor set from one
    observation cannot tell a healthy layer that moved from a broken one.
    """
    if manifest.adapter.type != "arcgis":
        return []
    params = arcgis_mod.ArcGISParams.model_validate(
        manifest.adapter.model_dump(exclude={"type"}))
    out = []
    for layer in sorted(params.layers):
        try:
            health = await ctx.arcgis.health(manifest, layer)
        except CommonwealthError as err:
            out.append({"layer": layer, "error": f"{err.code}: {err}"})
            continue
        out.append({"layer": layer,
                    "feature_count": health["feature_count"],
                    "min_expected": health["min_expected"],
                    "healthy": health["healthy"]})
    return out


# --- the accumulated readings ---------------------------------------------

def load_history() -> dict:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {"readings": []}


def record_readings(history: dict, when: str,
                    probes: dict[str, list[dict]]) -> dict:
    """Append this run's counts. Nothing is ever rewritten.

    A floor set from a range needs the range, and the range is only
    knowable if the readings accumulate. `sources probe` prints them and
    throws them away, which is why #19 sat open with the data it needed
    passing through a terminal on every run.

    One reading per layer per calendar day. Two runs twenty minutes apart
    are not two observations of how much a count moves, and counting them
    as two would make a floor look better evidenced than it is.
    """
    day = when[:10]
    seen = {(r["source_id"], r["layer"], r["observed_at"][:10])
            for r in history["readings"]}
    for source_id, layers in sorted(probes.items()):
        for entry in layers:
            # An error is not a count. Recording one would put a zero in
            # the range and drag every floor derived from it down.
            if "feature_count" not in entry:
                continue
            if (source_id, entry["layer"], day) in seen:
                continue
            history["readings"].append({
                "observed_at": when,
                "source_id": source_id,
                "layer": entry["layer"],
                "feature_count": entry["feature_count"],
                "min_expected": entry["min_expected"],
            })
            seen.add((source_id, entry["layer"], day))
    return history


def backfill_from_fixtures(history: dict) -> int:
    """Seed the history from readings already sitting in the fixtures.

    Every `sources sample` run wrote a `health:<layer>` block into the
    fixture summary with the live feature count of that day, and those
    readings went nowhere afterwards. They are real observations, dated by
    the fixture's own `recorded_at`, and they are exactly what #19 needed:
    a floor set from one reading cannot tell a healthy layer that moved
    from a broken one.

    Run once. Re-running adds nothing, because a reading is keyed by
    (source, layer, date) and duplicates are skipped.
    """
    seen = {(r["source_id"], r["layer"], r["observed_at"])
            for r in history["readings"]}
    added = 0
    for fixture in sorted(FIXTURES.glob("*/recorded.json")):
        doc = json.loads(fixture.read_text())
        source_id = doc.get("source_id") or fixture.parent.name
        when = doc.get("recorded_at")
        if not when:
            continue
        for key, value in (doc.get("summary") or {}).items():
            if not key.startswith("health:") or not isinstance(value, dict):
                continue
            count = value.get("feature_count")
            if not isinstance(count, int):
                continue
            layer = value.get("layer") or key.split(":", 1)[1]
            if (source_id, layer, when) in seen:
                continue
            history["readings"].append({
                "observed_at": when,
                "source_id": source_id,
                "layer": layer,
                "feature_count": count,
                "min_expected": value.get("min_expected"),
                "note": "backfilled from the committed fixture's own "
                        "recording, 2026-09-02",
            })
            seen.add((source_id, layer, when))
            added += 1
    history["readings"].sort(key=lambda r: (r["source_id"], r["layer"],
                                            r["observed_at"]))
    return added


def observed_range(history: dict, source_id: str, layer: str) -> dict | None:
    """Every reading for one layer, as a range. None when there are none."""
    counts = [r["feature_count"] for r in history["readings"]
              if r["source_id"] == source_id and r["layer"] == layer
              and isinstance(r.get("feature_count"), int)]
    if not counts:
        return None
    return {"observations": len(counts), "low": min(counts),
            "high": max(counts),
            "spread_pct": round((max(counts) - min(counts))
                                / max(counts) * 100, 1) if max(counts) else 0.0}


# --- the report ------------------------------------------------------------

def render(when: str, results: dict, probes: dict,
           history: dict) -> str:
    changed = sorted(sid for sid, r in results.items() if r["findings"])
    clean = sorted(sid for sid, r in results.items()
                   if r["status"] == "checked" and not r["findings"])
    skipped = sorted(sid for sid, r in results.items()
                     if r["status"] in ("no_fixture", "no_endpoint"))
    broken = sorted(sid for sid, r in results.items()
                    if r["status"] in ("unreachable", "partly_unreachable"))

    lines = [
        f"# Upstream drift, {when[:10]}",
        "",
        "Every committed fixture replayed against the live service it was "
        "recorded from, and every active layer counted. Written by "
        "`tools/upstream_audit.py`.",
        "",
        "Drift is the expected output. Government services rename fields, "
        "renumber layers, and change projections, and the value of this "
        "file is knowing when rather than finding out during a query.",
        "",
        f"- **{len(changed)} changed**",
        f"- **{len(clean)} checked, unchanged**",
        f"- **{len(broken)} could not be reached**",
        f"- **{len(skipped)} nothing to check** (no fixture, or no endpoint "
        "by design)",
        "",
    ]

    if changed:
        lines += ["## Changed", ""]
        for sid in changed:
            lines += [f"### `{sid}`", ""]
            for finding in results[sid]["findings"]:
                lines.append(f"- `{finding['request']}`")
                for note in finding["notes"]:
                    lines.append(f"  - {note}")
            lines.append("")

    lines += ["## Feature counts", "",
              "The `range` column is every reading this file has ever "
              "recorded for that layer, which is what a floor set from a "
              "range rather than a single observation needs.", "",
              "| Source | Layer | Count | Floor | Range so far | Readings |",
              "|---|---|---|---|---|---|"]
    for sid in sorted(probes):
        for entry in probes[sid]:
            if "error" in entry:
                lines.append(f"| `{sid}` | {entry['layer']} | — | — | "
                             f"{entry['error']} | — |")
                continue
            seen = observed_range(history, sid, entry["layer"])
            span = (f"{seen['low']:,}–{seen['high']:,} "
                    f"({seen['spread_pct']}%)" if seen else "—")
            mark = "" if entry["healthy"] else " **under floor**"
            lines.append(
                f"| `{sid}` | {entry['layer']} | {entry['feature_count']:,}"
                f"{mark} | {entry['min_expected']:,} | {span} | "
                f"{seen['observations'] if seen else 0} |")
    lines.append("")

    if broken:
        lines += ["## Could not be reached", "",
                  "Being unable to check is the one outcome this job treats "
                  "as a problem. A source here is not known to be healthy "
                  "or drifted.", ""]
        for sid in broken:
            lines.append(f"- `{sid}`: "
                         f"{results[sid]['unreachable']} request(s) failed")
        lines.append("")

    lines += ["## Checked, unchanged", "",
              "Listed by name on purpose: an empty diff and a source that "
              "was never visited are different facts.", ""]
    for sid in clean:
        lines.append(f"- `{sid}` ({results[sid]['checked']} requests)")
    lines.append("")

    if skipped:
        lines += ["## Nothing to check", ""]
        for sid in skipped:
            reason = ("no committed fixture"
                      if results[sid]["status"] == "no_fixture"
                      else "inventory only, no endpoint by design")
            lines.append(f"- `{sid}`: {reason}")
        lines.append("")
    return "\n".join(lines)


# --- entry point -----------------------------------------------------------

async def run(source_id: str | None) -> tuple[dict, dict]:
    ctx = load_context()
    results: dict[str, dict] = {}
    probes: dict[str, list[dict]] = {}

    ids = [source_id] if source_id else sorted(ctx.sources.manifests)
    for sid in ids:
        manifest = ctx.sources.get(sid)
        if manifest is None:
            raise SystemExit(f"unknown source {sid!r}")
        if manifest.adapter.type in NO_ENDPOINT:
            results[sid] = {"status": "no_endpoint", "checked": 0,
                            "findings": []}
            continue
        if manifest.adapter.type == "virginia_law":
            results[sid] = await _replay_pages(ctx, manifest, sid)
            continue
        fixture = FIXTURES / sid / "recorded.json"
        if not fixture.exists():
            results[sid] = {"status": "no_fixture", "checked": 0,
                            "findings": []}
        else:
            results[sid] = await _replay(manifest,
                                         json.loads(fixture.read_text()))
        layers = await _probe(ctx, manifest)
        if layers:
            probes[sid] = layers
    return results, probes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default=None,
                    help="One source id instead of the whole registry.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be checked and send nothing.")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write the report here instead of docs/audits/.")
    ap.add_argument("--backfill", action="store_true",
                    help="Seed the reading history from the committed "
                         "fixtures' own recorded counts, then exit. One "
                         "time; duplicates are skipped.")
    args = ap.parse_args()

    if args.backfill:
        history = load_history()
        added = backfill_from_fixtures(history)
        AUDITS.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(history, indent=1) + "\n")
        print(f"{HISTORY.relative_to(ROOT)}: {added} reading(s) backfilled, "
              f"{len(history['readings'])} total")
        return 0

    if args.dry_run:
        ctx = load_context()
        for sid in sorted(ctx.sources.manifests):
            fixture = FIXTURES / sid / "recorded.json"
            n = (len(json.loads(fixture.read_text()).get("exchanges") or [])
                 if fixture.exists() else 0)
            print(f"{sid}: {n} recorded request(s)")
        return 0

    when = _now()
    try:
        results, probes = asyncio.run(run(args.source))
    except Exception as err:  # noqa: BLE001 — the one real failure mode
        print(f"error: the audit could not run: "
              f"{err.__class__.__name__}: {err}", file=sys.stderr)
        return 1

    history = record_readings(load_history(), when, probes)
    history["readings"].sort(key=lambda r: (r["source_id"], r["layer"],
                                            r["observed_at"]))
    AUDITS.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=1) + "\n")

    out = args.out or AUDITS / f"upstream-{when[:10]}.md"
    out.write_text(render(when, results, probes, history) + "\n")

    changed = sum(1 for r in results.values() if r["findings"])
    unreachable = sum(1 for r in results.values()
                      if r["status"] in ("unreachable", "partly_unreachable"))
    print(f"{out.relative_to(ROOT)}: {len(results)} sources, "
          f"{changed} changed, {unreachable} unreachable")
    print(f"{HISTORY.relative_to(ROOT)}: "
          f"{len(history['readings'])} readings recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
