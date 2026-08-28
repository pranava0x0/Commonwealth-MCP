#!/usr/bin/env python3
"""Condense fetched HN threads into one readable digest.

Reads research/raw/hn/thread_*.json (produced by search_hn.py) and writes
comments_digest.md: for each thread, the top comments by position (HN ranks
by quality) with HTML stripped and long comments truncated. Root comments
carry more independent signal than deep replies, so depth is capped.

The point: a person or model can read one ~100KB file instead of 30 raw
JSON trees.

Usage:
  python3 tools/digest_hn_threads.py
  python3 tools/digest_hn_threads.py --per-thread 30 --max-chars 700
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HN_DIR = ROOT / "research" / "raw" / "hn"


def clean(text: str) -> str:
    text = re.sub(r"<p>", "\n", text)
    text = re.sub(r"<a href=\"([^\"]+)\"[^>]*>[^<]*</a>", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-thread", type=int, default=25)
    ap.add_argument("--max-chars", type=int, default=600)
    ap.add_argument("--max-depth", type=int, default=1,
                    help="Deepest reply level to include (default 1).")
    ap.add_argument("--out", type=Path, default=HN_DIR / "comments_digest.md")
    args = ap.parse_args()

    threads = sorted(HN_DIR.glob("thread_*.json"))
    if not threads:
        print("no thread_*.json found; run tools/search_hn.py first")
        return 1

    out = ["# HN comment digest", "",
           f"{len(threads)} threads; up to {args.per_thread} comments each, "
           f"depth <= {args.max_depth}, {args.max_chars} chars per comment.",
           ""]
    for path in threads:
        t = json.loads(path.read_text())
        picked = [c for c in t["comments"]
                  if c["depth"] <= args.max_depth][:args.per_thread]
        out.append(f"## [{t.get('points') or '?'}p] {t.get('title')}")
        out.append(f"{t['hn_url']}  ({t['comment_count']} comments total, "
                   f"{len(picked)} shown)")
        out.append("")
        for c in picked:
            body = clean(c["text"])
            if len(body) > args.max_chars:
                body = body[:args.max_chars] + " […]"
            indent = "  > " if c["depth"] else "- "
            body = body.replace("\n", " ")
            out.append(f"{indent}**{c['author']}**: {body}")
        out.append("")

    args.out.write_text("\n".join(out) + "\n")
    print(f"{len(threads)} threads -> {args.out} "
          f"({args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
