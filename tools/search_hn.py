#!/usr/bin/env python3
"""Pull Hacker News stories and comment threads about MCP.

Replaces an agent doing manual HN searches. Uses the Algolia HN Search API
(no key needed). Two passes:

  1. Story search across a fixed query list (override with --query).
  2. Full comment fetch for the top --threads stories by points, so the
     synthesis step reads what practitioners actually said, not just titles.

Output: research/raw/hn/stories.json and research/raw/hn/thread_<id>.json,
plus a stories.md digest for humans.

Usage:
  python3 tools/search_hn.py
  python3 tools/search_hn.py --query "MCP security" --min-points 20
  python3 tools/search_hn.py --threads 25
  python3 tools/search_hn.py --ids 46207425 48592163   # specific threads only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetchlib import FetchError, get_json  # noqa: E402

log = logging.getLogger("search_hn")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "raw" / "hn"

API = "https://hn.algolia.com/api/v1"

# Queries chosen to surface both the enthusiasm and the criticism. MCP the
# acronym collides with other meanings pre-2024, so searches are date-bounded.
DEFAULT_QUERIES = [
    '"Model Context Protocol"',
    "MCP server",
    "MCP security",
    "MCP registry",
    "MCP tools context",
    "code execution MCP",
    "MCP gateway",
    "MCP OAuth",
    "building MCP",
]
LAUNCH_DATE = "2024-11-01"  # MCP announced 2024-11-25; small margin.


def search_stories(query: str, min_points: int, since: str,
                   pages: int = 2) -> list[dict]:
    since_ts = int(time.mktime(time.strptime(since, "%Y-%m-%d")))
    hits: list[dict] = []
    for page in range(pages):
        params = urllib.parse.urlencode({
            "query": query,
            "tags": "story",
            "numericFilters": f"points>={min_points},created_at_i>={since_ts}",
            "hitsPerPage": 50,
            "page": page,
        })
        data = get_json(f"{API}/search?{params}")
        hits.extend(data.get("hits", []))
        if page + 1 >= data.get("nbPages", 0):
            break
        time.sleep(0.5)
    return hits


def fetch_thread(story_id: int) -> dict:
    """Full story tree including comments, via the items endpoint."""
    return get_json(f"{API}/items/{story_id}")


def flatten_comments(node: dict, depth: int = 0,
                     out: list[dict] | None = None) -> list[dict]:
    if out is None:
        out = []
    for child in node.get("children", []):
        text = child.get("text") or ""
        if text:
            out.append({
                "id": child.get("id"),
                "author": child.get("author"),
                "depth": depth,
                "points": child.get("points"),
                "text": text,
            })
        flatten_comments(child, depth + 1, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", action="append", default=None,
                    help="Search query (repeatable). Default: built-in list.")
    ap.add_argument("--min-points", type=int, default=40,
                    help="Minimum story points (default 40).")
    ap.add_argument("--since", default=LAUNCH_DATE,
                    help=f"Earliest story date, YYYY-MM-DD (default {LAUNCH_DATE}).")
    ap.add_argument("--threads", type=int, default=15,
                    help="Fetch full comments for the top N stories (default 15).")
    ap.add_argument("--ids", type=int, nargs="*", default=None,
                    help="Skip searching; fetch comments for these story IDs.")
    ap.add_argument("--out", type=Path, default=OUT_DIR,
                    help="Output directory (default research/raw/hn).")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    queries = args.query or DEFAULT_QUERIES
    args.out.mkdir(parents=True, exist_ok=True)

    if args.ids:
        for sid in args.ids:
            path = args.out / f"thread_{sid}.json"
            if path.exists():
                log.info("thread %s already fetched, skipping", sid)
                continue
            tree = fetch_thread(sid)
            comments = flatten_comments(tree)
            path.write_text(json.dumps({
                "id": sid, "title": tree.get("title"),
                "points": tree.get("points"),
                "hn_url": f"https://news.ycombinator.com/item?id={sid}",
                "comment_count": len(comments), "comments": comments},
                indent=1))
            log.info("thread %-10s %4d comments  %s", sid, len(comments),
                     (tree.get("title") or "")[:70])
            time.sleep(0.5)
        print(f"fetched {len(args.ids)} threads by id -> {args.out}")
        return 0

    seen: dict[str, dict] = {}
    for q in queries:
        try:
            hits = search_stories(q, args.min_points, args.since)
        except FetchError as err:
            log.error("query %r failed: %s", q, err)
            return 1
        log.info("query %-32r -> %d hits", q, len(hits))
        for h in hits:
            entry = seen.setdefault(h["objectID"], {
                "id": int(h["objectID"]),
                "title": h.get("title"),
                "url": h.get("url"),
                "points": h.get("points"),
                "num_comments": h.get("num_comments"),
                "created_at": h.get("created_at"),
                "author": h.get("author"),
                "hn_url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                "matched_queries": [],
            })
            entry["matched_queries"].append(q)
        time.sleep(0.5)

    stories = sorted(seen.values(), key=lambda s: -(s["points"] or 0))
    (args.out / "stories.json").write_text(
        json.dumps({"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "min_points": args.min_points, "since": args.since,
                    "queries": queries, "stories": stories}, indent=1))
    log.info("wrote %d unique stories -> %s", len(stories),
             args.out / "stories.json")

    fetched = 0
    for s in stories[:args.threads]:
        path = args.out / f"thread_{s['id']}.json"
        if path.exists():
            log.info("thread %s already fetched, skipping", s["id"])
            continue
        try:
            tree = fetch_thread(s["id"])
        except FetchError as err:
            log.error("thread %s failed: %s", s["id"], err)
            continue
        comments = flatten_comments(tree)
        path.write_text(json.dumps({
            "id": s["id"], "title": s["title"], "points": s["points"],
            "hn_url": s["hn_url"], "comment_count": len(comments),
            "comments": comments}, indent=1))
        fetched += 1
        log.info("thread %-10s %4d comments  %s", s["id"], len(comments),
                 (s["title"] or "")[:70])
        time.sleep(0.5)

    digest = ["# HN stories about MCP", "",
              f"Fetched {time.strftime('%Y-%m-%d')}; "
              f"min {args.min_points} points since {args.since}; "
              f"{len(stories)} unique stories.", ""]
    for s in stories:
        digest.append(f"- [{s['points']:>4} pts, {s['num_comments'] or 0:>4} comments] "
                      f"{s['title']}  \n  {s['hn_url']}")
    (args.out / "stories.md").write_text("\n".join(digest) + "\n")

    print(f"{len(stories)} stories, {fetched} new threads with comments "
          f"-> {args.out}")
    if not stories:
        print("zero stories is unexpected for these queries; "
              "check network or loosen --min-points", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
