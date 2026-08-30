"""Shared fixtures: replay fetching over recorded government responses.

House rule (TESTING.md): mocks replay REAL recorded responses, never
synthesized shapes. `tests/fixtures/sources/*/recorded.json` is written by
`commonwealth sources sample` against the live service; the one deliberate
mutation (a conflicting district for the two-source disagreement test) is
derived from the recording and labeled where it is made.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from commonwealth.adapters.arcgis import ArcGISAdapter
from commonwealth.adapters.base import TTLCache
from commonwealth.adapters.virginia_law import VirginiaLawAdapter
from commonwealth.core.jurisdiction import JurisdictionTable
from commonwealth.core.registry import SourceManifest, SourceRegistry
from commonwealth.runtime import PROJECT_ROOT, SOURCES_DIR, RuntimeContext

FIXTURES = Path(__file__).parent / "fixtures"
FAIRFAX_FIXTURE = FIXTURES / "sources" / "va-fairfax-parcels-zoning" / "recorded.json"
CIVIC_FIXTURE_DIR = FIXTURES / "sources" / "va-code-of-virginia"
CIVIC_SERVICE_URL = "https://law.lis.virginia.gov/vacode"

SECONDARY_HOST = "secondary.example.gov"
SECONDARY_URL = f"https://{SECONDARY_HOST}/arcgis/rest/services/Mirror/FeatureServer"


def load_recording() -> dict:
    if not FAIRFAX_FIXTURE.exists():
        pytest.fail(f"missing recorded fixture {FAIRFAX_FIXTURE}; run "
                    "`commonwealth sources sample va-fairfax-parcels-zoning`")
    return json.loads(FAIRFAX_FIXTURE.read_text())


# Shared with the site/demo generator; re-exported here so tests keep one
# import path.
from commonwealth.adapters.replay import (HtmlReplayFetcher,  # noqa: E402,F401
                                          ReplayFetcher)


def load_civic_pages() -> dict[str, tuple[str, str]]:
    """The two recorded law.lis.virginia.gov pages (a real section, and
    the real redirect-landing page for a section the site doesn't have),
    keyed by the request URL the adapter actually builds."""
    found_html = (CIVIC_FIXTURE_DIR / "section-1-500.html").read_text()
    not_found_html = (CIVIC_FIXTURE_DIR / "no-such-section.html").read_text()
    return {
        f"{CIVIC_SERVICE_URL}/1-500/": (
            found_html, f"{CIVIC_SERVICE_URL}/1-500/"),
        f"{CIVIC_SERVICE_URL}/1-999999/": (
            not_found_html, f"{CIVIC_SERVICE_URL}/title1/"),
    }


def _real_manifest() -> SourceManifest:
    import yaml
    path = SOURCES_DIR / "local" / "fairfax-county" / "parcels-zoning.yaml"
    return SourceManifest.model_validate(yaml.safe_load(path.read_text()))


def make_secondary_manifest() -> SourceManifest:
    """A synthetic second source for two-source (0005-C) tests: same shape as
    the real recording, different host and authority level."""
    m = _real_manifest().model_dump()
    m["id"] = "va-fairfax-secondary-mirror"
    m["name"] = "Synthetic secondary mirror (test only)"
    m["publisher"]["authority_level"] = "official_secondary"
    m["adapter"]["service_url"] = SECONDARY_URL
    return SourceManifest.model_validate(m)


def secondary_exchanges(mutate_district: str | None = None) -> list[dict]:
    """The real recording re-keyed to the secondary host; optionally with the
    zoning district mutated to force a cross-source conflict (the one
    sanctioned mutation — shape stays the recorded shape)."""
    recording = load_recording()
    primary_url = _real_manifest().adapter.model_dump()["service_url"]
    out = []
    for ex in recording["exchanges"]:
        ex2 = copy.deepcopy(ex)
        ex2["url"] = ex["url"].replace(primary_url, SECONDARY_URL)
        if mutate_district is not None:
            for feat in (ex2["response"].get("features") or []):
                attrs = feat.get("attributes", {})
                if "ZONECODE" in attrs:
                    attrs["ZONECODE"] = mutate_district
        out.append(ex2)
    return out


@pytest.fixture()
def recording() -> dict:
    return load_recording()


@pytest.fixture()
def sample_pin(recording) -> str:
    pin = recording["summary"]["sample_pin"]
    assert pin, "recorded fixture carries no sample_pin"
    return pin


def load_all_recordings() -> list[dict]:
    """Every committed source's own fixture, merged. `build_ctx` loads the
    real (multi-source) registry, so a query against one jurisdiction can
    legitimately reach more than one source (../design/architecture.md decision 0005-C) — the replay
    pool has to cover whichever ones actually get queried, not just
    Fairfax's."""
    exchanges: list[dict] = []
    for path in sorted((FIXTURES / "sources").glob("*/recorded.json")):
        exchanges.extend(json.loads(path.read_text())["exchanges"])
    return exchanges


def build_ctx(extra_manifests: list[SourceManifest] | None = None,
              extra_exchanges: list[dict] | None = None,
              fetcher: object | None = None,
              civic_fetcher: object | None = None) -> RuntimeContext:
    exchanges = load_all_recordings() + list(extra_exchanges or [])
    replay = fetcher or ReplayFetcher(exchanges)
    civic_replay = civic_fetcher or HtmlReplayFetcher(load_civic_pages())
    real = SourceRegistry.load(SOURCES_DIR)
    manifests = list(real.manifests.values()) + list(extra_manifests or [])
    registry = SourceRegistry(manifests, real.capability_vocab, real.revision)
    return RuntimeContext(
        sources=registry,
        jurisdictions=JurisdictionTable.load(SOURCES_DIR / "jurisdictions"),
        arcgis=ArcGISAdapter(fetcher=replay, cache=TTLCache()),
        virginia_law=VirginiaLawAdapter(fetcher=civic_replay))


@pytest.fixture()
def cw_ctx() -> RuntimeContext:
    """Context over the real registry with replayed Fairfax responses."""
    return build_ctx()


@pytest.fixture()
def project_root() -> Path:
    return PROJECT_ROOT
