"""W3C trace context, carried from the tool call through the adapter
calls it makes (GitHub issue #36; design/architecture.md § 23).

§ 23 chose OpenTelemetry conventions over a bespoke logging story, and
the MCP spec carries trace context in a request's `_meta` as
`traceparent`/`tracestate`. What was missing was the middle: a tool call
fanned out to several government services and every log line it produced
looked like an unrelated request, so "which requests did this call
make?" could only be answered by reading timestamps and guessing.

This is the plumbing, not an exporter. There is nowhere to send spans
until this is hosted, which is what #36 says and still holds. What
changes is that the ids exist and are attached, so the answer is already
in the logs and an exporter later has something real to read.

**Nothing is sent upstream.** A government ArcGIS server is not a
participant in this trace: it will not continue it, nothing will collect
its spans, and adding a header those services never asked for changes
what this project puts on the wire to them for no one's benefit. So the
trace context propagates INTO adapter calls and into what this project
logs, and stops at the egress boundary. If that ever changes it should
change deliberately, per host, in a manifest.
"""
from __future__ import annotations

import contextvars
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass

# version "-" trace-id(32 hex) "-" parent-id(16 hex) "-" flags(2 hex).
#
# Only version 00 is defined, and it is exactly these four fields. A later
# version may append fields after another dash, and the spec asks a parser
# that does not know that version to read the first four and ignore the
# rest — so the tail is allowed for any version but 00. Version `ff` is
# reserved as invalid outright: a header carrying it is malformed and
# starts a new trace, rather than being continued (found in review of
# PR #56; this regex used to accept it).
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})"
    r"(?P<tail>-[^\s]*)?$")
_INVALID_VERSION = "ff"

# All-zero ids are explicitly invalid in the spec, and treating one as a
# real trace would group every such call under one id.
_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16

# `tracestate` is vendor data this project neither reads nor writes; it is
# carried verbatim so a client's own state survives the hop. Capped
# because it arrives from outside: the spec's own limit is 512 bytes.
MAX_TRACESTATE_BYTES = 512


@dataclass(frozen=True)
class TraceContext:
    """One point in a trace: which trace, which span, and whether the
    client asked for it to be recorded."""

    trace_id: str
    span_id: str
    sampled: bool = True
    tracestate: str | None = None

    def traceparent(self) -> str:
        return (f"00-{self.trace_id}-{self.span_id}-"
                f"{'01' if self.sampled else '00'}")

    def child(self) -> "TraceContext":
        """A new span in the same trace. One per outbound request, so the
        requests a single tool call makes are siblings under it rather
        than indistinguishable."""
        return TraceContext(trace_id=self.trace_id, span_id=new_span_id(),
                            sampled=self.sampled, tracestate=self.tracestate)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(value: object,
                      tracestate: object = None) -> TraceContext | None:
    """A client's `traceparent`, or None if it is absent or malformed.

    Malformed is not an error and not a reason to fail a tool call: the
    spec says a receiver that cannot parse the field starts a new trace.
    Refusing the call would let a broken caller header take a government
    lookup down.

    Typed `object` rather than `str` because the values come out of the
    request's `_meta`, which is caller JSON: a number or a list arrives
    here as easily as a string, and is as malformed as any other
    unparseable header (review of PR #56: `.strip()` on one raised
    before the tool ran).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    match = _TRACEPARENT.match(value.strip())
    if not match:
        return None
    version = match.group("version")
    if version == _INVALID_VERSION:
        return None
    if version == "00" and match.group("tail"):
        # Version 00 is defined as exactly four fields. Trailing data on
        # it is a malformed header, not a newer one.
        return None
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if trace_id == _ZERO_TRACE or span_id == _ZERO_SPAN:
        return None
    state = tracestate.strip() if isinstance(tracestate, str) else ""
    if not state or len(state.encode()) > MAX_TRACESTATE_BYTES:
        # Truncating vendor state would corrupt it; dropping it loses
        # nothing this project uses. A non-string is dropped the same
        # way: it is not vendor state, it is a malformed field.
        state = None
    return TraceContext(
        trace_id=trace_id,
        # The client's span is this call's PARENT. This call is a new
        # span under it, which is what makes the tool call a unit in the
        # trace rather than a relabelling of the caller's span.
        span_id=new_span_id(),
        sampled=bool(int(match.group("flags"), 16) & 0x01),
        tracestate=state)


_current: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "commonwealth_trace", default=None)


def current_trace() -> TraceContext | None:
    return _current.get()


@contextmanager
def trace_call(traceparent: object = None,
               tracestate: object = None,
               trace_id: str | None = None):
    """Bind a trace for the duration of one tool call.

    Continues the caller's trace when they sent a usable `traceparent`,
    and otherwise starts one. `trace_id` lets the caller pin it to an id
    it already has — the server passes the envelope's `request_id`, so a
    locally-started trace and the audit record it produces carry the same
    identifier instead of two unrelated ones a reader has to join.

    A ContextVar rather than an argument threaded through every adapter:
    the adapters are reached through several call shapes, and a parameter
    added to all of them is a parameter some future one forgets. Context
    vars are per-task, so concurrent tool calls do not see each other's.
    """
    parent = parse_traceparent(traceparent, tracestate)
    if parent is None:
        parent = TraceContext(
            trace_id=(trace_id if trace_id and _is_trace_id(trace_id)
                      else new_trace_id()),
            span_id=new_span_id())
    token = _current.set(parent)
    try:
        yield parent
    finally:
        _current.reset(token)


def _is_trace_id(value: str) -> bool:
    return (len(value) == 32 and value != _ZERO_TRACE
            and all(c in "0123456789abcdef" for c in value.lower()))


def trace_fields() -> dict[str, str]:
    """What to attach to a log line or an audit record, or nothing at all.

    Empty when no trace is bound, so a CLI run or a test that never
    started one is not decorated with invented ids.
    """
    ctx = current_trace()
    if ctx is None:
        return {}
    return {"trace_id": ctx.trace_id, "span_id": ctx.span_id}


# Whether outbound requests to government services carry the trace
# header. Off, for the reason in the module docstring: those services are
# not participants in this trace. It is an environment switch rather than
# a constant so an operator running this behind their own gateway — where
# the next hop IS theirs and does collect spans — can turn it on without
# patching the code, and so the default is a decision someone can see.
def propagate_upstream() -> bool:
    return os.environ.get("COMMONWEALTH_TRACE_UPSTREAM", "").lower() in (
        "1", "true", "yes")
