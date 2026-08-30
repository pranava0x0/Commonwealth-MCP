"""Build a RuntimeContext that replays the committed recordings.

The offline seam, shared by the test suite, the site generator, and the
`examples/` scripts. It lives in the package rather than under `tests/`
so a script someone runs can reach it without importing a test module —
`design/testing-and-demos.md` § 3 asks for demos that work with no
network, and importing pytest fixtures to get one would be a strange
thing to hand a newcomer.

Every fixture under `tests/fixtures/sources/` is written by
`commonwealth sources sample` against the live service. Nothing here
synthesizes a response.
"""
from __future__ import annotations

import json
from pathlib import Path

from .adapters.arcgis import ArcGISAdapter
from .adapters.arcgis_geocode import ArcGISGeocodeAdapter
from .adapters.base import TTLCache
from .adapters.replay import HtmlReplayFetcher, ReplayFetcher
from .adapters.virginia_law import VirginiaLawAdapter
from .core.jurisdiction import JurisdictionTable
from .core.registry import SourceRegistry
from .runtime import PROJECT_ROOT, SOURCES_DIR, RuntimeContext

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "sources"
CIVIC_FIXTURE_DIR = FIXTURES_DIR / "va-code-of-virginia"
CIVIC_SERVICE_URL = "https://law.lis.virginia.gov/vacode"


def recorded_exchanges() -> list[dict]:
    """Every committed source's recorded JSON exchanges, merged.

    One pool rather than one per source, because a single query can
    legitimately reach more than one source (decision 0005-C) and the
    replay has to cover whichever ones actually get queried."""
    exchanges: list[dict] = []
    for path in sorted(FIXTURES_DIR.glob("*/recorded.json")):
        exchanges.extend(json.loads(path.read_text())["exchanges"])
    if not exchanges:
        raise FileNotFoundError(
            f"no recorded fixtures under {FIXTURES_DIR}; run "
            "`commonwealth sources sample <source-id>`")
    return exchanges


def recorded_pages() -> dict[str, tuple[str, str]]:
    """The recorded law.lis.virginia.gov pages, keyed by the URL the
    adapter builds: a real section, and the real redirect-landing page for
    a section the site does not have."""
    found = (CIVIC_FIXTURE_DIR / "section-1-500.html").read_text()
    missing = (CIVIC_FIXTURE_DIR / "no-such-section.html").read_text()
    return {
        f"{CIVIC_SERVICE_URL}/1-500/": (found,
                                        f"{CIVIC_SERVICE_URL}/1-500/"),
        f"{CIVIC_SERVICE_URL}/1-999999/": (missing,
                                           f"{CIVIC_SERVICE_URL}/title1/"),
    }


def replay_context(sources_dir: Path | None = None) -> RuntimeContext:
    """A context whose adapters replay the recordings instead of reaching
    the network. Unknown requests fail loudly — a replay that silently
    returned nothing would make every consumer vacuous."""
    root = sources_dir or SOURCES_DIR
    exchanges = recorded_exchanges()
    return RuntimeContext(
        sources=SourceRegistry.load(root),
        jurisdictions=JurisdictionTable.load(root / "jurisdictions"),
        arcgis=ArcGISAdapter(fetcher=ReplayFetcher(exchanges),
                             cache=TTLCache()),
        geocoder=ArcGISGeocodeAdapter(fetcher=ReplayFetcher(exchanges),
                                      cache=TTLCache()),
        virginia_law=VirginiaLawAdapter(
            fetcher=HtmlReplayFetcher(recorded_pages())))
