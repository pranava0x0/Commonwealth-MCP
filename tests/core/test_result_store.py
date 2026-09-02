"""The result store (../../design/architecture.md decision 0013; GitHub issue #33).

The envelope has carried a `resources` field since the first version and
it was always empty, because `EnvelopeBuilder` had no way to add one. What
that cost was concrete: `geo.find_boundaries` generalized every polygon to
roughly 22 m and had nowhere to put the publisher's own vertices, and
`geo.find_buildings` retrieved hundreds of footprints and dropped all but
25 of them.

These tests are written against the four things 0013 asks the store to get
right, each of which is a claim the project makes elsewhere.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from commonwealth.core.registry import (DataClassification, SourceManifest,
                                        SourceRegistry)
from commonwealth.core.results import (DEFAULT_TTL_SECONDS, KINDS,
                                       MAX_STORED_BYTES, DiskResultStore,
                                       MemoryResultStore, ResultUnavailable,
                                       RetentionForbidden, resource_ref,
                                       retention_allowed)
from commonwealth.runtime import SOURCES_DIR


@pytest.fixture(scope="module")
def manifest() -> SourceManifest:
    m = SourceRegistry.load(SOURCES_DIR).get("va-vgin-admin-boundaries")
    assert m is not None, "the boundary source is the store's first caller"
    return m


@pytest.fixture(params=["memory", "disk"])
def store(request, tmp_path):
    """Both backends, every test.

    The disk one is what ships and the memory one is what the tests and the
    site generator use, so a rule enforced by only one of them is a rule
    the offline suite would describe wrongly.
    """
    if request.param == "memory":
        return MemoryResultStore()
    return DiskResultStore(root=tmp_path / "results")


def _put(store, manifest, **over):
    kwargs = dict(kind="results", payload={"features": [1, 2, 3]},
                  media_type="application/json", manifests=[manifest],
                  origin_tool="geo.find_boundaries",
                  origin_arguments={"jurisdiction": "Fairfax County",
                                    "detail": "full"})
    kwargs.update(over)
    return store.put(**kwargs)


# --- identity and round trip ----------------------------------------------

def test_a_stored_payload_comes_back_unchanged(store, manifest):
    stored = _put(store, manifest)
    assert store.get(stored.uri).payload == {"features": [1, 2, 3]}


def test_ids_are_128_bits_and_unguessable(store, manifest):
    """0013's figure. A counter or a hash of the query would let anyone
    holding one handle construct another, which matters the moment this
    is hosted and two callers share a store."""
    ids = {_put(store, manifest).id for _ in range(25)}
    assert len(ids) == 25, "ids repeated"
    for ident in ids:
        assert len(ident) == 32 and int(ident, 16) >= 0, ident


def test_the_uri_says_which_kind_of_thing_is_behind_it(store, manifest):
    for kind in KINDS:
        stored = _put(store, manifest, kind=kind)
        assert stored.uri.startswith(f"commonwealth://{kind}/")
        assert store.get(stored.uri).kind == kind


def test_a_handle_read_under_the_wrong_kind_does_not_resolve(store,
                                                             manifest):
    stored = _put(store, manifest, kind="results")
    with pytest.raises(ResultUnavailable) as err:
        store.get(stored.uri.replace("/results/", "/evidence/"))
    assert err.value.reason == "not_found"


@pytest.mark.parametrize("uri", [
    "https://example.gov/results/abc",
    "commonwealth://nonsense/abc",
    "commonwealth://results/",
    "not a uri at all",
])
def test_a_uri_this_server_never_mints_is_refused(store, uri):
    with pytest.raises(ResultUnavailable):
        store.get(uri)


# --- expiry ---------------------------------------------------------------

def test_the_expiry_is_stamped_and_defaults_to_a_day(store, manifest):
    stored = _put(store, manifest)
    expires = datetime.strptime(stored.expires_at, "%Y-%m-%dT%H:%M:%SZ")
    stored_at = datetime.strptime(stored.stored_at, "%Y-%m-%dT%H:%M:%SZ")
    assert abs((expires - stored_at).total_seconds()
               - DEFAULT_TTL_SECONDS) <= 2


def test_an_expired_handle_reads_as_expired_not_as_missing(store, manifest):
    """The house rule about kinds of empty, one level down. A caller told
    "no such result" re-runs nothing and concludes the answer never
    existed; a caller told "expired" knows exactly what to do."""
    stored = _put(store, manifest, ttl_seconds=-1)
    with pytest.raises(ResultUnavailable) as err:
        store.get(stored.uri)
    assert err.value.reason == "expired"
    assert "expired" in str(err.value)


def test_an_expired_handle_names_the_call_that_would_rebuild_it(store,
                                                                manifest):
    stored = _put(store, manifest, ttl_seconds=-1)
    with pytest.raises(ResultUnavailable) as err:
        store.get(stored.uri)
    message = str(err.value)
    assert "geo.find_boundaries" in message
    assert "Fairfax County" in message


def test_the_sweep_removes_expired_payloads_and_leaves_live_ones(store,
                                                                 manifest):
    live = _put(store, manifest)
    dead = [_put(store, manifest, ttl_seconds=-1) for _ in range(3)]
    assert store.sweep() == 3
    assert store.get(live.uri).payload
    for stored in dead:
        with pytest.raises(ResultUnavailable):
            store.get(stored.uri)
    assert store.sweep() == 0, "a second sweep has nothing left to do"


# --- terms ----------------------------------------------------------------

def test_the_write_time_classification_travels_with_the_bytes(store,
                                                              manifest):
    stored = _put(store, manifest)
    assert stored.classification == \
        manifest.access.data_classification.value
    assert store.get(stored.uri).classification == stored.classification


def test_the_strictest_classification_wins_when_sources_are_mixed(
        store, manifest):
    sensitive = manifest.model_copy(deep=True)
    sensitive.access.data_classification = \
        DataClassification.sensitive_public
    stored = _put(store, manifest, manifests=[manifest, sensitive])
    assert stored.classification == "sensitive_public", (
        "mixing an open source with a sensitive one must not launder it")


def test_a_source_whose_terms_forbid_retention_is_refused_at_write(
        store, manifest):
    forbidden = manifest.model_copy(deep=True)
    forbidden.access.retention = "forbidden"
    assert retention_allowed(forbidden) is False
    with pytest.raises(RetentionForbidden) as err:
        _put(store, manifest, manifests=[forbidden])
    assert forbidden.id in str(err.value)


def test_a_restricted_source_is_refused_even_without_the_flag(store,
                                                              manifest):
    """`restricted` cannot be active at all, so storing its payload would
    be answering a question that should never have been asked."""
    restricted = manifest.model_copy(deep=True)
    restricted.access.data_classification = DataClassification.restricted
    assert retention_allowed(restricted) is False
    with pytest.raises(RetentionForbidden):
        _put(store, manifest, manifests=[restricted])


def test_every_registered_source_may_be_retained_today(manifest):
    """Derived, so registering a source with a retention condition shows
    up here rather than silently disabling handles for it."""
    registry = SourceRegistry.load(SOURCES_DIR)
    blocked = [m.id for m in registry.manifests.values()
               if not retention_allowed(m)]
    assert blocked == [], (
        f"{blocked} cannot be stored; the tools that would hand out a "
        "handle for them must say so instead of returning one")


# --- limits ---------------------------------------------------------------

def test_a_payload_over_the_cap_is_refused(store, manifest):
    with pytest.raises(ValueError, match="store cap"):
        _put(store, manifest,
             payload={"pad": "x" * (MAX_STORED_BYTES + 1)})


def test_an_unknown_kind_is_refused(store, manifest):
    with pytest.raises(ValueError, match="kind must be"):
        _put(store, manifest, kind="whatever")


# --- the envelope entry ---------------------------------------------------

def test_the_resource_ref_carries_the_expiry_and_the_rebuild_call(store,
                                                                  manifest):
    """A caller who has to look up when a handle dies is a caller who will
    use it too late."""
    stored = _put(store, manifest)
    ref = resource_ref(stored, "Fairfax County's boundary.")
    assert ref.uri == stored.uri
    assert stored.expires_at in ref.description
    assert "geo.find_boundaries" in ref.description


# --- the two processes share one store ------------------------------------

def test_a_handle_minted_by_one_process_resolves_in_another(tmp_path,
                                                            manifest):
    """The CLI and the server are separate processes over one directory,
    which is what makes a handle printed by `commonwealth tools call`
    readable from the server (and the same shape #20's shared rate limit
    will need)."""
    writer = DiskResultStore(root=tmp_path / "shared")
    stored = _put(writer, manifest)
    reader = DiskResultStore(root=tmp_path / "shared")
    assert reader.get(stored.uri).payload == {"features": [1, 2, 3]}


def test_a_half_written_file_never_resolves(tmp_path, manifest):
    """Written beside and renamed, so a crash mid-write leaves no
    resolvable handle rather than a truncated one."""
    store = DiskResultStore(root=tmp_path / "results")
    stored = _put(store, manifest)
    path = tmp_path / "results" / f"{stored.id}.json"
    assert path.exists() and json.loads(path.read_text())["id"] == stored.id
    assert not list((tmp_path / "results").glob("*.partial"))


def test_an_unreadable_file_is_swept_rather_than_kept(tmp_path, manifest):
    store = DiskResultStore(root=tmp_path / "results")
    _put(store, manifest)
    (tmp_path / "results" / "garbage.json").write_text("{not json")
    assert store.sweep() == 1
    assert not (tmp_path / "results" / "garbage.json").exists()
