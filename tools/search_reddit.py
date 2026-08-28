#!/usr/bin/env python3
"""Pull top Reddit threads about building MCP servers.

Reddit's public JSON endpoints (www/old/api.reddit.com) now serve a JS app
shell or a bot challenge to non-browser clients from many networks,
including the one this script was first written on (verified 2026-08-26:
all three hosts, three User-Agent variants, plus the pullpush.io mirror —
every one blocked). The script still tries, because the block is
network-dependent, and fails loud with the fallback plan when refused.

Fallbacks, in order of preference:
  1. Run this script from a network where reddit.com/.json works
     (typically residential; the block keys on IP reputation).
  2. Authenticated OAuth API with a script app (client id + secret in
     REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars) — implemented below,
     used automatically when the env vars are set.
  3. Web-search snippets (site:reddit.com queries through any search tool).
     Lower fidelity: titles and fragments, not full threads.

Output: research/raw/reddit/<sub>_top.json per subreddit.

Usage:
  python3 tools/search_reddit.py
  python3 tools/search_reddit.py --sub mcp --sub ClaudeAI --time year
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetchlib import USER_AGENT, FetchError, get_json  # noqa: E402

log = logging.getLogger("search_reddit")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "raw" / "reddit"

DEFAULT_SUBS = ["mcp", "modelcontextprotocol", "ClaudeAI", "LocalLLaMA"]
SEARCH_QUERIES = ["MCP server best practices", "building MCP server",
                  "MCP tools too many", "MCP security"]


def oauth_token() -> str | None:
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["access_token"]


def listing(path: str, params: dict[str, str], token: str | None) -> dict:
    base = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return get_json(url, headers=headers)


def slim_post(child: dict) -> dict:
    d = child.get("data", {})
    return {"title": d.get("title"), "score": d.get("score"),
            "num_comments": d.get("num_comments"),
            "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
            "created_utc": d.get("created_utc"),
            "selftext": (d.get("selftext") or "")[:2000],
            "subreddit": d.get("subreddit")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sub", action="append", default=None,
                    help="Subreddit (repeatable). Default: built-in list.")
    ap.add_argument("--time", default="year",
                    choices=["month", "year", "all"])
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    subs = args.sub or DEFAULT_SUBS
    args.out.mkdir(parents=True, exist_ok=True)

    token = None
    try:
        token = oauth_token()
    except Exception as err:  # noqa: BLE001 — report and continue unauthenticated
        log.warning("OAuth token fetch failed (%s); trying unauthenticated", err)
    if token:
        log.info("using authenticated OAuth API")

    wrote = 0
    for sub in subs:
        try:
            data = listing(f"/r/{sub}/top.json",
                           {"t": args.time, "limit": str(args.limit),
                            "raw_json": "1"}, token)
        except FetchError as err:
            log.error("r/%s blocked or failed: %s", sub, err)
            continue
        posts = [slim_post(c) for c in data.get("data", {}).get("children", [])]
        (args.out / f"{sub}_top.json").write_text(json.dumps({
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "subreddit": sub, "time_filter": args.time,
            "posts": posts}, indent=1))
        log.info("r/%s: %d posts", sub, len(posts))
        wrote += 1
        time.sleep(1.0)

    # Keyword search across all of Reddit, same access path.
    if wrote:
        results: list[dict] = []
        for q in SEARCH_QUERIES:
            try:
                data = listing("/search.json",
                               {"q": q, "sort": "top", "t": args.time,
                                "limit": "25", "raw_json": "1"}, token)
                results += [{**slim_post(c), "query": q}
                            for c in data.get("data", {}).get("children", [])]
            except FetchError as err:
                log.error("search %r failed: %s", q, err)
            time.sleep(1.0)
        (args.out / "keyword_search.json").write_text(
            json.dumps({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "results": results}, indent=1))

    if wrote == 0:
        print("Reddit refused every request (JS shell / bot challenge).\n"
              "Fallbacks: run from a residential network, set "
              "REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET for OAuth, or use "
              "web-search snippets (site:reddit.com). See docstring.",
              file=sys.stderr)
        return 1
    print(f"{wrote}/{len(subs)} subreddits -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
