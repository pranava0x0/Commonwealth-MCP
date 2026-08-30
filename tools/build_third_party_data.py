#!/usr/bin/env python3
"""Generate THIRD_PARTY_DATA.yml from the source manifests.

Decision 0011 requires an inventory of the government content this repo
redistributes, because the CC0 dedication over `sources/` covers only what
the project wrote. A recorded fixture is the publisher's content and the
publisher's terms travel with it.

Generated rather than hand-written, for the same reason the catalog is: a
hand-maintained second copy of a derivable list goes stale, and a stale
list here would misstate somebody's licensing terms.

    python3 tools/build_third_party_data.py           # write the file
    python3 tools/build_third_party_data.py --check    # verify it is current
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THIRD_PARTY_DATA.yml"

HEADER = """\
# Government content this repository redistributes, and whose terms it is
# under. GENERATED — do not edit by hand.
#
#   regenerate:  python3 tools/build_third_party_data.py
#   verify:      python3 tools/build_third_party_data.py --check
#
# The CC0 dedication in sources/LICENSE covers the manifests this project
# wrote. It does not cover the responses recorded from these services. Read
# a source's own terms before redistributing anything recorded from it.
#
# `automation_status` is what the publisher's terms say about automated
# access, as reviewed on `terms_reviewed_at`. `unknown` means nobody has
# reviewed it yet, and such a source cannot go active.
"""


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "sources"


def orphaned_fixtures(known_ids: set[str]) -> list[str]:
    """Fixture directories with no manifest behind them.

    The inventory is built by walking manifests, so deleting a manifest or
    changing its `id` silently drops its recorded government responses from
    this file while those files stay in the tree. That is the moment the
    licensing record most needs to notice them, so they are listed rather
    than omitted.
    """
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(d.name for d in FIXTURE_ROOT.iterdir()
                  if d.is_dir() and d.name not in known_ids)


def manifests() -> list[dict]:
    out = []
    for path in sorted((ROOT / "sources").rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict) or "id" not in doc or "access" not in doc:
            continue
        access = doc.get("access") or {}
        fixtures = sorted(
            str(p.relative_to(ROOT))
            for p in (ROOT / "tests" / "fixtures" / "sources" / doc["id"]).rglob("*")
            if p.is_file()
        )
        out.append({
            "id": doc["id"],
            "name": doc.get("name"),
            "publisher": (doc.get("publisher") or {}).get("agency"),
            "manifest": str(path.relative_to(ROOT)),
            "terms_url": access.get("terms_url"),
            "terms_reviewed_at": access.get("terms_reviewed_at"),
            "automation_status": access.get("automation_status", "unknown"),
            "data_classification": access.get("data_classification"),
            "recorded_fixtures": fixtures,
        })
    return out


def render(rows: list[dict] | None = None) -> str:
    rows = manifests() if rows is None else rows
    doc: dict = {"sources": rows}
    orphans = orphaned_fixtures({r["id"] for r in rows})
    if orphans:
        doc["orphaned_fixture_directories"] = orphans
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=78)
    return HEADER + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="Exit non-zero if the file is stale, or if a "
                         "fixture directory has no manifest behind it.")
    args = ap.parse_args()

    rows = manifests()
    text = render(rows)
    orphans = orphaned_fixtures({r["id"] for r in rows})
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print("THIRD_PARTY_DATA.yml is stale; run "
                  "tools/build_third_party_data.py", file=sys.stderr)
            return 1
        if orphans:
            print(f"fixture directories with no manifest: "
                  f"{', '.join(orphans)}", file=sys.stderr)
            return 1
        print(f"THIRD_PARTY_DATA.yml current ({len(rows)} sources)")
        return 0

    OUT.write_text(text)
    print(f"wrote {OUT.name}: {len(rows)} sources")
    if orphans:
        print(f"  warning: {len(orphans)} fixture director"
              f"{'y' if len(orphans) == 1 else 'ies'} with no manifest: "
              f"{', '.join(orphans)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
