#!/usr/bin/env python3
"""Survey the MCP ecosystem on GitHub.

Replaces an agent doing manual repo searches. Three sweeps:

  1. Top MCP repos by stars (topic:mcp plus name searches) — who leads the
     ecosystem and how big the field is.
  2. Civic/government-data MCP repos — anything overlapping Commonwealth's
     ground: open data portals, GIS, Socrata, ArcGIS, CKAN, GTFS, Legistar,
     municipal/state government.
  3. Watchlist repos named in the reference-architecture doc — current stars,
     last push, description, so the doc's snapshot can be re-dated.

Uses `gh` (authenticated, 30 search calls/min) when available, otherwise the
unauthenticated API (10/min — the script sleeps to respect it).

Output: research/raw/github/*.json plus a summary.md digest.

Usage:
  python3 tools/search_github.py
  python3 tools/search_github.py --sweep civic
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetchlib import FetchError, get_json  # noqa: E402

log = logging.getLogger("search_github")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "raw" / "github"

TOP_QUERIES = [
    "topic:mcp stars:>1000",
    "topic:mcp-server stars:>500",
    '"mcp server" in:name,description stars:>1000',
]

CIVIC_QUERIES = [
    "mcp government in:name,description,readme",
    "mcp civic in:name,description",
    'mcp "open data" in:name,description',
    "mcp socrata in:name,description,readme",
    "mcp arcgis in:name,description",
    "mcp ckan in:name,description",
    "mcp gtfs in:name,description",
    "mcp legistar in:name,description,readme",
    "mcp municipal in:name,description,readme",
    "mcp census in:name,description",
    "mcp zoning in:name,description,readme",
    "mcp permits in:name,description,readme",
    "mcp geospatial in:name,description",
]

# Repos the reference-architecture evaluation already reviewed, plus the
# frequently recommended ones worth tracking. Sweep 3 re-dates them.
WATCHLIST = [
    "pnnl/nepa-mcp",
    "Power-Agent/PowerMCP",
    "Power-Agent/PowerSkills",
    "Power-Agent/PowerAgentBench",
    "GSA-TTS/mcp-server-hub-catalog",
    "github/github-mcp-server",
    "cloudflare/mcp-server-cloudflare",
    "cloudflare/mcp",
    "upstash/context7",
    "awslabs/mcp",
    "microsoft/playwright-mcp",
    "modelcontextprotocol/servers",
    "modelcontextprotocol/registry",
    "modelcontextprotocol/python-sdk",
    "modelcontextprotocol/typescript-sdk",
    "modelcontextprotocol/inspector",
    "jlowin/fastmcp",
    "getsentry/sentry-mcp",
    "stripe/agent-toolkit",
    "makenotion/notion-mcp-server",
    "supabase-community/supabase-mcp",
    "grafana/mcp-grafana",
    "docker/mcp-registry",
    "obot-platform/obot",
    "IBM/mcp-context-forge",
]

FIELDS = ("full_name", "description", "stargazers_count", "pushed_at",
          "created_at", "archived", "fork", "language", "license",
          "topics", "html_url")


def _slim(repo: dict) -> dict:
    out = {k: repo.get(k) for k in FIELDS}
    lic = out.get("license")
    if isinstance(lic, dict):
        out["license"] = lic.get("spdx_id")
    return out


def have_gh() -> bool:
    if not shutil.which("gh"):
        return False
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True)
    return proc.returncode == 0


def gh_api(path: str) -> dict:
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode != 0:
        raise FetchError(f"gh api {path}: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


def search_repos(query: str, use_gh: bool, per_page: int = 30) -> list[dict]:
    q = urllib.parse.quote(query)
    path = f"search/repositories?q={q}&sort=stars&order=desc&per_page={per_page}"
    if use_gh:
        data = gh_api(path)
    else:
        data = get_json(f"https://api.github.com/{path}")
        time.sleep(6.5)  # unauthenticated search: 10 requests/minute
    return [_slim(r) for r in data.get("items", [])]


def fetch_repo(full_name: str, use_gh: bool) -> dict:
    path = f"repos/{full_name}"
    if use_gh:
        return _slim(gh_api(path))
    data = get_json(f"https://api.github.com/{path}")
    time.sleep(1.0)
    return _slim(data)


def run_sweep(name: str, queries: list[str], use_gh: bool) -> list[dict]:
    seen: dict[str, dict] = {}
    for q in queries:
        try:
            repos = search_repos(q, use_gh)
        except FetchError as err:
            log.error("query %r failed: %s", q, err)
            continue
        log.info("[%s] %-55r -> %d repos", name, q, len(repos))
        for r in repos:
            entry = seen.setdefault(r["full_name"], {**r, "matched_queries": []})
            entry["matched_queries"].append(q)
        if use_gh:
            time.sleep(2.1)  # authenticated search: 30 requests/minute
    return sorted(seen.values(), key=lambda r: -(r["stargazers_count"] or 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep", choices=["top", "civic", "watchlist", "all"],
                    default="all")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args.out.mkdir(parents=True, exist_ok=True)
    use_gh = have_gh()
    log.info("github access via %s", "gh CLI (authenticated)" if use_gh
             else "unauthenticated API (throttled)")

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    summary: list[str] = [f"# GitHub MCP ecosystem sweep — {stamp[:10]}", ""]

    if args.sweep in ("top", "all"):
        top = run_sweep("top", TOP_QUERIES, use_gh)
        (args.out / "top_repos.json").write_text(
            json.dumps({"fetched_at": stamp, "repos": top}, indent=1))
        summary += [f"## Top repos by stars ({len(top)})", ""]
        summary += [f"- {r['stargazers_count']:>6}★ `{r['full_name']}` — "
                    f"{(r['description'] or '')[:110]}" for r in top[:40]]
        summary.append("")

    if args.sweep in ("civic", "all"):
        civic = run_sweep("civic", CIVIC_QUERIES, use_gh)
        (args.out / "civic_repos.json").write_text(
            json.dumps({"fetched_at": stamp, "repos": civic}, indent=1))
        summary += [f"## Civic / government-data repos ({len(civic)})", ""]
        summary += [f"- {r['stargazers_count']:>6}★ `{r['full_name']}` "
                    f"(pushed {str(r['pushed_at'])[:10]}) — "
                    f"{(r['description'] or '')[:110]}" for r in civic[:60]]
        summary.append("")

    if args.sweep in ("watchlist", "all"):
        watch: list[dict] = []
        missing: list[str] = []
        for full_name in WATCHLIST:
            try:
                watch.append(fetch_repo(full_name, use_gh))
            except (FetchError, json.JSONDecodeError) as err:
                log.warning("watchlist %s: %s", full_name, err)
                missing.append(full_name)
        (args.out / "watchlist.json").write_text(
            json.dumps({"fetched_at": stamp, "repos": watch,
                        "not_found": missing}, indent=1))
        summary += [f"## Watchlist ({len(watch)} found, {len(missing)} missing)", ""]
        summary += [f"- {r['stargazers_count']:>6}★ `{r['full_name']}` "
                    f"(pushed {str(r['pushed_at'])[:10]}"
                    f"{', ARCHIVED' if r['archived'] else ''})"
                    for r in watch]
        if missing:
            summary += ["", "Not found (renamed or moved?):"]
            summary += [f"- {m}" for m in missing]

    (args.out / "summary.md").write_text("\n".join(summary) + "\n")
    print(f"sweep '{args.sweep}' done -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
