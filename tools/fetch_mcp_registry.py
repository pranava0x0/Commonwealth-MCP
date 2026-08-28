#!/usr/bin/env python3
"""Snapshot the official MCP Registry (registry.modelcontextprotocol.io).

Replaces an agent browsing registry listings. Pages through /v0/servers,
saves the full listing, and writes a digest: total count, remote vs package
distribution, transport types, and any servers matching civic/government
keywords.

The registry is the ecosystem's source of truth for public server metadata;
Commonwealth will eventually publish its own servers there, so the snapshot
also serves as a schema reference (see raw/registry/sample_entry.json).

Usage:
  python3 tools/fetch_mcp_registry.py
  python3 tools/fetch_mcp_registry.py --max-pages 5   # quick sample
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetchlib import FetchError, get_json  # noqa: E402

log = logging.getLogger("fetch_mcp_registry")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "raw" / "registry"
API = "https://registry.modelcontextprotocol.io/v0/servers"

CIVIC_KEYWORDS = ("government", "civic", "municipal", "county", "city",
                  "state", "census", "open data", "opendata", "socrata",
                  "arcgis", "gis", "zoning", "permit", "legislat", "transit",
                  "gtfs", "procurement", "ckan", "federal", "congress",
                  "regulation")


def fetch_all(max_pages: int) -> list[dict]:
    servers: list[dict] = []
    cursor: str | None = None
    for page in range(max_pages):
        params = {"limit": "100"}
        if cursor:
            params["cursor"] = cursor
        data = get_json(f"{API}?{urllib.parse.urlencode(params)}")
        batch = data.get("servers", [])
        servers.extend(batch)
        cursor = (data.get("metadata") or {}).get("nextCursor") or (
            data.get("metadata") or {}).get("next_cursor")
        log.info("page %d: %d servers (total %d)", page + 1, len(batch),
                 len(servers))
        if not cursor or not batch:
            return servers
        time.sleep(0.3)
    log.warning("stopped at --max-pages=%d with more pages remaining; "
                "the snapshot is PARTIAL", max_pages)
    return servers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-pages", type=int, default=200,
                    help="Page cap, 100 servers/page (default 200).")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args.out.mkdir(parents=True, exist_ok=True)
    try:
        servers = fetch_all(args.max_pages)
    except FetchError as err:
        log.error("registry fetch failed: %s", err)
        return 1
    if not servers:
        log.error("registry returned zero servers; that is not a real "
                  "snapshot — check the API path or network")
        return 1

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    (args.out / "servers.json").write_text(
        json.dumps({"fetched_at": stamp, "count": len(servers),
                    "servers": servers}, indent=1))
    (args.out / "sample_entry.json").write_text(json.dumps(servers[0], indent=2))

    remotes = 0
    packages: collections.Counter[str] = collections.Counter()
    transports: collections.Counter[str] = collections.Counter()
    civic: list[dict] = []
    for wrapper in servers:
        srv = wrapper.get("server", wrapper)
        if srv.get("remotes"):
            remotes += 1
            for r in srv["remotes"]:
                transports[r.get("type", "unknown")] += 1
        for pkg in srv.get("packages") or []:
            packages[pkg.get("registryType")
                     or pkg.get("registry_type") or "unknown"] += 1
        text = " ".join(str(srv.get(k, "")) for k in
                        ("name", "title", "description")).lower()
        if any(k in text for k in CIVIC_KEYWORDS):
            civic.append({"name": srv.get("name"),
                          "description": srv.get("description")})

    digest = [
        f"# MCP Registry snapshot — {stamp[:10]}", "",
        f"- Total servers listed: {len(servers)}",
        f"- With remote endpoints: {remotes}",
        f"- Remote transport types: {dict(transports)}",
        f"- Package registry types: {dict(packages)}",
        f"- Matching civic/government keywords: {len(civic)}", "",
        "## Civic/government keyword matches", "",
    ]
    digest += [f"- `{c['name']}` — {(c['description'] or '')[:130]}"
               for c in civic]
    (args.out / "digest.md").write_text("\n".join(digest) + "\n")

    print(f"{len(servers)} servers ({remotes} remote, {len(civic)} civic "
          f"matches) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
