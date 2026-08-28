"""Toolsnaps (design/testing-and-demos.md, github-mcp-server's pattern):
every tool's wire contract — description, annotations, input and output
schema — is snapshot-committed. Changing a tool means updating its snap in
the same reviewed diff; a drifted snap fails here.

Regenerate deliberately:  .venv/bin/python tests/test_toolsnaps.py
"""
import asyncio
import json
from pathlib import Path

SNAPS_DIR = Path(__file__).parent / "toolsnaps"


def _current_snaps() -> dict[str, dict]:
    from mcp.client import Client
    from commonwealth.servers.build import build_server
    from tests.conftest import build_ctx

    async def collect() -> dict[str, dict]:
        server = build_server(build_ctx(), profile="all")
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
        return {
            t.name: {
                "description": t.description,
                "annotations": t.annotations.model_dump(mode="json",
                                                        exclude_none=True)
                if t.annotations else None,
                "input_schema": t.input_schema,
                "output_schema": t.output_schema,
            } for t in tools}

    return asyncio.run(collect())


def test_toolsnaps_match_registered_contracts():
    current = _current_snaps()
    assert current, "no tools registered — snapshot basis vanished"
    committed_files = {p.stem.replace("__", "."): p
                       for p in SNAPS_DIR.glob("*.json")}
    missing = sorted(set(current) - set(committed_files))
    stale = sorted(set(committed_files) - set(current))
    assert not missing, (f"tools without committed snaps: {missing} — "
                         "regenerate via `python tests/test_toolsnaps.py`")
    assert not stale, (f"snaps for tools that no longer exist: {stale} — "
                       "a rename needs a deprecation alias "
                       "(core/toolreg.py) plus snap update")
    diffs = []
    for name, snap in current.items():
        committed = json.loads(committed_files[name].read_text())
        if committed != snap:
            diffs.append(name)
    assert diffs == [], (f"tool contracts drifted from committed snaps: "
                         f"{diffs} — review the change, then regenerate")
    print(f"toolsnaps checked for {len(current)} tools")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    SNAPS_DIR.mkdir(exist_ok=True)
    snaps = _current_snaps()
    for name, snap in snaps.items():
        path = SNAPS_DIR / (name.replace(".", "__") + ".json")
        path.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(snaps)} toolsnaps -> {SNAPS_DIR}")
