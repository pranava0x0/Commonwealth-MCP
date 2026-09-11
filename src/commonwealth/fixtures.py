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

from .adapters.agenda_platform import AgendaPlatformAdapter
from .adapters.arcgis import ArcGISAdapter
from .adapters.arcgis_geocode import ArcGISGeocodeAdapter
from .adapters.base import TTLCache
from .adapters.replay import HtmlReplayFetcher, ReplayFetcher
from .adapters.virginia_law import VirginiaLawAdapter
from .core.jurisdiction import JurisdictionTable
from .core.registry import SourceRegistry
from .core.results import MemoryResultStore
from .runtime import PROJECT_ROOT, SOURCES_DIR, RuntimeContext

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "sources"
CIVIC_FIXTURE_DIR = FIXTURES_DIR / "va-code-of-virginia"
CIVIC_SERVICE_URL = "https://law.lis.virginia.gov/vacode"
CIVIC_SEARCH_URL = "https://law.lis.virginia.gov/search_cov"


def fixture_names() -> list[str]:
    """Every recorded fixture directory, by name.

    Every directory, not every `recorded.json`. The Code of Virginia's
    recordings are `api-recorded.json` plus a handful of HTML pages,
    because its two endpoints answer in different formats and merging
    its JSON into the ArcGIS pool would put one publisher's shapes in
    another's replay. It is still a fixture, and a task declaring it
    should not be told it does not exist.
    """
    return sorted(p.name for p in FIXTURES_DIR.iterdir()
                  if p.is_dir() and any(p.iterdir()))


def recorded_exchanges(only: list[str] | None = None) -> list[dict]:
    """Every committed source's recorded JSON exchanges, merged.

    One pool rather than one per source, because a single query can
    legitimately reach more than one source (decision 0005-C) and the
    replay has to cover whichever ones actually get queried.

    `only` narrows the pool to the named fixture directories, which is
    how a bench task's declared `fixtures:` becomes enforceable rather
    than decorative: with the pool narrowed, a task that reaches an
    undeclared recording fails on the replay instead of quietly passing
    on inputs it never declared. An unknown name is an error, not an
    empty pool — a typo that silently narrowed to nothing would make
    every task using it fail for the wrong reason.
    """
    if only is not None:
        known = set(fixture_names())
        unknown = sorted(set(only) - known)
        if unknown:
            raise FileNotFoundError(
                f"no recorded fixture directory named {unknown} under "
                f"{FIXTURES_DIR}; known fixtures are {sorted(known)}")
        # Only the directories that contribute to THIS pool. A declared
        # fixture whose recordings are a different format (the Code of
        # Virginia's HTML pages and JSON API) contributes nothing here
        # and is wired separately by `replay_context`, so it is skipped
        # rather than treated as a missing file.
        paths = [path for name in sorted(set(only))
                 if (path := FIXTURES_DIR / name / "recorded.json").exists()]
    else:
        paths = sorted(FIXTURES_DIR.glob("*/recorded.json"))

    exchanges: list[dict] = []
    for path in paths:
        exchanges.extend(json.loads(path.read_text())["exchanges"])
    if not exchanges and only is None:
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
    # The section a browse walk reaches in the recorded table of contents
    # (title 15.2, chapter 22), so walking to a citation and reading it
    # replays as one path rather than two halves that only look joined.
    walked = (CIVIC_FIXTURE_DIR / "section-15.2-2200.html").read_text()
    # The publisher's own full-text search, recorded 2026-09-09 answering
    # exactly what it has answered every query since 2026-08-28: "The
    # Search Appliance is down." Nothing reads this endpoint — it is here
    # so the health watch over it (GitHub issue #12) replays offline like
    # everything else, and so the page a recovery would replace is on
    # disk to diff against.
    search_down = (CIVIC_FIXTURE_DIR / "search-appliance-down.html"
                   ).read_text()
    search_url = f"{CIVIC_SEARCH_URL}?query=zoning"
    return {
        search_url: (search_down, f"{CIVIC_SEARCH_URL}/"),
        f"{CIVIC_SERVICE_URL}/1-500/": (found,
                                        f"{CIVIC_SERVICE_URL}/1-500/"),
        f"{CIVIC_SERVICE_URL}/1-999999/": (missing,
                                           f"{CIVIC_SERVICE_URL}/title1/"),
        f"{CIVIC_SERVICE_URL}/15.2-2200/": (
            walked, f"{CIVIC_SERVICE_URL}/15.2-2200/"),
    }


def recorded_api_exchanges() -> list[dict]:
    """The Code of Virginia's JSON API recordings.

    Kept in `api-recorded.json` rather than `recorded.json` so the ArcGIS
    replay pool, which merges every `recorded.json` in the tree, does not
    also carry a different publisher's JSON-API shapes.
    """
    path = CIVIC_FIXTURE_DIR / "api-recorded.json"
    return json.loads(path.read_text())["exchanges"]


def fixture_vintage(name: str) -> str | None:
    """When a fixture directory was recorded, from its own file.

    Most directories carry `recorded.json`; the Code of Virginia's JSON
    recordings are `api-recorded.json` (its HTML pages carry no date, so
    the API recording is the directory's vintage). None when neither
    exists or neither says.
    """
    for filename in ("recorded.json", "api-recorded.json"):
        path = FIXTURES_DIR / name / filename
        if path.exists():
            return json.loads(path.read_text()).get("recorded_at")
    return None


# What a replay seam holds when a caller declared fixtures and this one
# was not among them. ReplayFetcher and HtmlReplayFetcher refuse to be
# built empty, because for every other caller empty means an unloaded
# fixture; one entry nothing will ever request keeps that check honest
# and makes any real request against this seam fail as unrecorded.
_UNDECLARED = "commonwealth://no-fixtures-declared"


def replay_context(fixtures: list[str] | None = None,
                   sources_dir: Path | None = None) -> RuntimeContext:
    """A context whose adapters replay the recordings instead of reaching
    the network. Unknown requests fail loudly — a replay that silently
    returned nothing would make every consumer vacuous.

    `fixtures` narrows the pool to those directories (see
    `recorded_exchanges`). A task or script that declares its inputs
    gets a context that can only answer from them. It comes first so
    this function is usable as the bench runner's `context_factory`
    without a lambda in between.
    """
    root = sources_dir or SOURCES_DIR
    exchanges = recorded_exchanges(fixtures)
    # A narrowed pool can legitimately be empty — a task whose expected
    # answer is a registry gap reaches no source at all — and
    # ReplayFetcher refuses to be built with nothing, because for every
    # other caller an empty pool means an unloaded fixture. One sentinel
    # exchange nothing will ever request keeps that check meaningful for
    # them and lets a no-source task run.
    pool = exchanges or [{"url": _UNDECLARED, "params": {}, "response": {}}]
    # The Code of Virginia's recordings are wired separately from the
    # ArcGIS pool, and they obey the same declaration: a caller that named
    # its fixtures and left this one out gets a Code replay that refuses
    # everything. It used to be wired unconditionally, so a task could
    # read a section it never declared (found in review of PR #56).
    code_declared = fixtures is None or CIVIC_FIXTURE_DIR.name in fixtures
    pages = (recorded_pages() if code_declared
             else {_UNDECLARED: ("", _UNDECLARED)})
    api = (recorded_api_exchanges() if code_declared
           else [{"url": _UNDECLARED, "params": {}, "response": {}}])
    return RuntimeContext(
        sources=SourceRegistry.load(root),
        jurisdictions=JurisdictionTable.load(root / "jurisdictions"),
        arcgis=ArcGISAdapter(fetcher=ReplayFetcher(pool), cache=TTLCache()),
        geocoder=ArcGISGeocodeAdapter(fetcher=ReplayFetcher(pool),
                                      cache=TTLCache()),
        virginia_law=VirginiaLawAdapter(
            fetcher=HtmlReplayFetcher(pages),
            json_fetcher=ReplayFetcher(api)),
        agendas=AgendaPlatformAdapter(fetcher=ReplayFetcher(pool)),
        results=MemoryResultStore(deterministic=True))
