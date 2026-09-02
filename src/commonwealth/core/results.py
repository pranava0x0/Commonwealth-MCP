"""The result store (../../../design/architecture.md decision 0013, Chosen).

Some answers do not fit in a model's context and must not be thrown away
for it. A jurisdiction boundary is a polygon with thousands of vertices; a
dense building query retrieves hundreds of footprints. Before this module
existed, `geo.find_boundaries` generalized the polygon to roughly 22 m and
`geo.find_buildings` kept 25 records and dropped the rest, and neither had
anywhere to put what it could not return.

What a tool does now: return the inline summary AND write the full payload
here, handing back a `commonwealth://` handle in the envelope's
`resources`. The handle is what makes the difference between "this answer
is abridged" and "this answer is abridged and here is the rest".

Four things this store is careful about, each because getting it wrong
would undo something the project claims elsewhere:

1. **Ids are unguessable.** 128 bits from `secrets`, never a counter and
   never derived from the query, because a guessable handle is a way to
   read someone else's result once this is hosted.
2. **Expiry is a fact the caller is told.** The envelope carries the
   expiry time, and reading an expired handle says `expired` rather than
   "no such result". Those are different facts, the same way an empty
   result and an uncovered jurisdiction are.
3. **Terms travel with the bytes.** The classification is recorded when
   the payload is written, from the manifest that produced it. A source
   whose terms forbid retention is refused at write time rather than
   filtered at read time.
4. **One interface, two processes.** The CLI and the server share a
   directory, so a handle minted by one resolves in the other. The disk
   backend is V1; a hosted deployment swaps it for an object store behind
   the same three methods.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .envelope import ResourceRef, utc_now_iso
from .errors import CommonwealthError
from .registry import DataClassification, SourceManifest

URI_SCHEME = "commonwealth"

# 0013's figure. A GeoJSON boundary for a large county with full vertex
# detail runs a few megabytes; 50 MB leaves room without becoming a place
# to park a dataset.
MAX_STORED_BYTES = 50_000_000

DEFAULT_TTL_SECONDS = 24 * 60 * 60

# The two handle kinds the provenance spec names. `results` holds a tool's
# full answer; `evidence` holds the raw record behind one claim
# (design/provenance-envelope.md § 2's `commonwealth://evidence/...`).
KINDS = ("results", "evidence")


class ResultUnavailable(CommonwealthError):
    """A handle did not resolve. `reason` separates the cases a caller has
    to tell apart: an expired handle means the answer existed and the
    window closed, and re-running the call will produce it again."""

    code = "ResultUnavailable"

    def __init__(self, msg: str, reason: str) -> None:
        super().__init__(msg)
        self.reason = reason  # expired | not_found | swept


class RetentionForbidden(CommonwealthError):
    """The manifest's terms say this publisher's bytes may not be kept.

    Raised at write time, so a tool that would have stored something it
    may not store fails loudly during development rather than quietly
    retaining it in production.
    """

    code = "RetentionForbidden"


def store_root() -> Path:
    """Where the disk backend lives.

    `COMMONWEALTH_RESULT_STORE` overrides it, which is what tests and a
    containerized deployment use. Otherwise the platform cache directory,
    because these are derived bytes with an expiry: losing the whole
    directory costs a re-query and nothing else.
    """
    override = os.environ.get("COMMONWEALTH_RESULT_STORE")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "commonwealth" / "results"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else home / "AppData" / "Local"
        return root / "commonwealth" / "results"
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else home / ".cache"
    return root / "commonwealth" / "results"


@dataclass(frozen=True)
class StoredResult:
    """One stored payload and everything needed to judge it on the way out."""

    id: str
    kind: str
    payload: Any
    media_type: str
    classification: str
    source_ids: tuple[str, ...]
    stored_at: str
    expires_at: str
    # How to get this answer again after the handle expires. 0013 requires
    # that an expired handle's error can say "re-run this call" as a
    # mechanical instruction rather than as advice.
    origin_tool: str
    origin_arguments: dict[str, Any]

    @property
    def uri(self) -> str:
        return f"{URI_SCHEME}://{self.kind}/{self.id}"


def _parse_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != URI_SCHEME:
        raise ResultUnavailable(
            f"{uri!r} is not a {URI_SCHEME}:// handle", "not_found")
    kind = parsed.netloc
    ident = parsed.path.lstrip("/")
    if kind not in KINDS or not ident:
        raise ResultUnavailable(
            f"{uri!r} is not a handle this server mints; expected "
            f"{URI_SCHEME}://<{'|'.join(KINDS)}>/<id>", "not_found")
    return kind, ident


def retention_allowed(manifest: SourceManifest) -> bool:
    """Whether this publisher's bytes may be held past the request.

    Two ways a manifest says no. `access.retention` is the explicit one, a
    terms fact a reviewer records. `data_classification: restricted` is
    the structural one — such a source cannot be active at all, and
    storing its payload would be the wrong answer to a question that
    should never have been asked.
    """
    if manifest.access.data_classification == DataClassification.restricted:
        return False
    return manifest.access.retention != "forbidden"


def build_record(*, kind: str, payload: Any, media_type: str,
                 manifests: list[SourceManifest], origin_tool: str,
                 origin_arguments: dict[str, Any],
                 ttl_seconds: int = DEFAULT_TTL_SECONDS
                 ) -> tuple[StoredResult, dict]:
    """Every check a write has to pass, and the record it produces.

    Shared by both backends rather than implemented twice: what the store
    refuses is policy, and a memory backend that refused less than the
    disk one would make the offline tests describe behaviour that does not
    ship.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")

    refused = [m.id for m in manifests if not retention_allowed(m)]
    if refused:
        raise RetentionForbidden(
            f"{origin_tool} tried to store a payload from {refused}, whose "
            "terms do not permit retention. Return the inline summary "
            "without a handle and say the full result cannot be kept.")

    size = len(json.dumps(payload, separators=(",", ":"),
                          default=str).encode())
    if size > MAX_STORED_BYTES:
        raise ValueError(
            f"{origin_tool} produced {size} bytes, over the "
            f"{MAX_STORED_BYTES}-byte store cap. Narrow the query rather "
            "than raising the cap.")

    now = datetime.now(timezone.utc)
    stored = StoredResult(
        id=secrets.token_hex(16),  # 128 bits, per 0013
        kind=kind, payload=payload, media_type=media_type,
        classification=_classification_of(manifests),
        source_ids=tuple(sorted(m.id for m in manifests)),
        stored_at=utc_now_iso(),
        expires_at=(now + timedelta(seconds=ttl_seconds)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        origin_tool=origin_tool, origin_arguments=origin_arguments)
    doc = {
        "id": stored.id, "kind": stored.kind,
        "media_type": stored.media_type,
        "classification": stored.classification,
        "source_ids": list(stored.source_ids),
        "stored_at": stored.stored_at, "expires_at": stored.expires_at,
        "origin_tool": stored.origin_tool,
        "origin_arguments": stored.origin_arguments,
        "payload": payload,
    }
    return stored, doc


def _resolve(doc: dict | None, kind: str, uri: str) -> StoredResult:
    """Turn a stored document into a result, or say why it cannot be one.

    The three refusals are deliberately distinguishable. A handle that was
    never minted, one whose window closed, and one asked for under the
    wrong kind are three different mistakes.
    """
    if doc is None:
        raise ResultUnavailable(
            f"No stored result for {uri}. A handle this server never "
            "minted and one already swept after expiry look the same "
            "here; if it came from an answer more than "
            f"{DEFAULT_TTL_SECONDS // 3600} hours old, it has expired and "
            "re-running the original call will produce it again.",
            "not_found")
    if doc["kind"] != kind:
        raise ResultUnavailable(
            f"{uri} names a {kind} handle and the stored result is a "
            f"{doc['kind']}", "not_found")
    stored = _from_doc(doc)
    if _expired(stored):
        raise ResultUnavailable(
            f"The result at {uri} expired at {stored.expires_at}. It "
            "existed and the retention window closed, which is not the "
            f"same as a missing result. Re-run {stored.origin_tool} with "
            f"{json.dumps(stored.origin_arguments, default=str)} to "
            "produce it again.", "expired")
    return stored


class ResultStore(Protocol):
    def put(self, *, kind: str, payload: Any, media_type: str,
            manifests: list[SourceManifest], origin_tool: str,
            origin_arguments: dict[str, Any],
            ttl_seconds: int = DEFAULT_TTL_SECONDS) -> StoredResult: ...

    def get(self, uri: str) -> StoredResult: ...

    def sweep(self) -> int: ...


@dataclass
class DiskResultStore:
    """One JSON file per handle under `root`, named by its id.

    A directory rather than a database because V1 runs as one local
    process and the whole store is disposable. These three methods are the
    interface a hosted object store implements later; nothing outside this
    module knows which backend is behind them.
    """

    root: Path | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root) if self.root is not None else store_root()

    def put(self, **kwargs) -> StoredResult:
        stored, doc = build_record(**kwargs)
        path = self._path(stored.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and renamed, so a reader never sees half a file
        # and a crash mid-write leaves no resolvable handle behind.
        tmp = path.with_suffix(".partial")
        tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str))
        tmp.replace(path)
        return stored

    def get(self, uri: str) -> StoredResult:
        kind, ident = _parse_uri(uri)
        path = self._path(ident)
        doc = json.loads(path.read_text()) if path.exists() else None
        return _resolve(doc, kind, uri)

    def sweep(self) -> int:
        """Delete every expired payload; returns how many went.

        Expiry is enforced on read as well, so an unswept store is correct
        and merely large. The sweep is about not holding bytes past the
        window their terms were judged against.
        """
        assert self.root is not None
        if not self.root.is_dir():
            return 0
        gone = 0
        for path in self.root.glob("*.json"):
            try:
                doc = json.loads(path.read_text())
                expired = _expired(_from_doc(doc))
            except (OSError, json.JSONDecodeError, KeyError):
                # An unreadable file cannot be resolved by any handle, so
                # keeping it serves nobody.
                expired = True
            if expired:
                path.unlink(missing_ok=True)
                gone += 1
        return gone

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _path(self, ident: str) -> Path:
        if not ident.isalnum():
            raise ResultUnavailable(f"{ident!r} is not a handle id",
                                    "not_found")
        assert self.root is not None
        return self.root / f"{ident}.json"


class MemoryResultStore:
    """The same store with nothing on disk behind it.

    Tests and the site generator use it so a run leaves nothing on the
    machine. Writes go through `build_record` and reads through
    `_resolve`, the same two functions the disk backend uses, so the two
    cannot disagree about what is refused or what has expired.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}

    def put(self, **kwargs) -> StoredResult:
        stored, doc = build_record(**kwargs)
        self._docs[stored.id] = doc
        return stored

    def get(self, uri: str) -> StoredResult:
        kind, ident = _parse_uri(uri)
        return _resolve(self._docs.get(ident), kind, uri)

    def sweep(self) -> int:
        gone = [k for k, doc in self._docs.items()
                if _expired(_from_doc(doc))]
        for key in gone:
            del self._docs[key]
        return len(gone)

    def clear(self) -> None:
        self._docs.clear()


def _classification_of(manifests: list[SourceManifest]) -> str:
    """The strictest classification among the sources that produced it.

    A payload assembled from an open source and a sensitive_public one is
    sensitive_public. Mixing does not launder it.
    """
    order = [DataClassification.open, DataClassification.sensitive_public,
             DataClassification.restricted]
    worst = DataClassification.open
    for m in manifests:
        if order.index(m.access.data_classification) > order.index(worst):
            worst = m.access.data_classification
    return worst.value


def _from_doc(doc: dict) -> StoredResult:
    return StoredResult(
        id=doc["id"], kind=doc["kind"], payload=doc["payload"],
        media_type=doc["media_type"], classification=doc["classification"],
        source_ids=tuple(doc["source_ids"]), stored_at=doc["stored_at"],
        expires_at=doc["expires_at"], origin_tool=doc["origin_tool"],
        origin_arguments=doc["origin_arguments"])


def _expired(stored: StoredResult) -> bool:
    return datetime.strptime(
        stored.expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc) <= datetime.now(timezone.utc)


def resource_ref(stored: StoredResult, description: str) -> ResourceRef:
    """The envelope entry for a stored payload.

    The description carries the expiry, because a caller who has to look
    up when a handle dies is a caller who will use it too late.
    """
    return ResourceRef(
        uri=stored.uri, media_type=stored.media_type,
        description=f"{description} Expires {stored.expires_at}; "
                    f"re-run {stored.origin_tool} to regenerate it.")


def prune_on_start(store: ResultStore) -> int:
    """Sweep once at process start.

    0013 asks for an expiry sweep and V1 has no scheduler, so the sweep
    runs when a process does. A machine that runs the CLI once a week
    still clears last week's payloads before writing this week's.
    """
    try:
        return store.sweep()
    except OSError:
        # A cache directory that cannot be read is not a reason to refuse
        # to answer questions.
        return 0
