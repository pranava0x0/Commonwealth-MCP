"""Trace context: parsing, propagation, and the boundary it stops at
(GitHub issue #36).
"""
import logging

import pytest
from mcp.client import Client

from commonwealth.core.tracing import (MAX_TRACESTATE_BYTES, TraceContext,
                                       current_trace, parse_traceparent,
                                       propagate_upstream, trace_call,
                                       trace_fields)
from commonwealth.servers.build import build_server
from tests.conftest import build_ctx

# A well-formed W3C header, version 00, sampled.
CLIENT_TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
CLIENT_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


# --- parsing ---------------------------------------------------------------

def test_a_valid_traceparent_is_continued_not_replaced():
    ctx = parse_traceparent(CLIENT_TRACE)
    assert ctx is not None
    assert ctx.trace_id == CLIENT_TRACE_ID
    # The caller's span is this call's parent, so this call gets its own.
    assert ctx.span_id != "00f067aa0ba902b7"
    assert ctx.sampled is True


def test_the_sampled_flag_is_read_from_the_header():
    unsampled = parse_traceparent(
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00")
    assert unsampled is not None and unsampled.sampled is False


@pytest.mark.parametrize("value", [
    None,
    "",
    "not-a-traceparent",
    "00-tooshort-00f067aa0ba902b7-01",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",   # no flags
    "00-4bf92f3577b34da6a3ce929d0e0e4736-XXf067aa0ba902b7-01",  # not hex
    # All-zero ids are invalid per the spec; treating one as real would
    # group every call that sent it under a single trace.
    "00-" + "0" * 32 + "-00f067aa0ba902b7-01",
    "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",
    # `_meta` is caller JSON, so these arrive as easily as a string
    # (review of PR #56: `.strip()` on one raised before the tool ran).
    1,
    1.5,
    True,
    [CLIENT_TRACE],
    {"traceparent": CLIENT_TRACE},
    CLIENT_TRACE.encode(),
])
def test_an_unusable_traceparent_is_ignored_rather_than_fatal(value):
    """A broken caller header must not be able to fail a lookup."""
    assert parse_traceparent(value) is None


def test_a_later_version_is_read_by_its_first_four_fields():
    """The spec asks a parser that does not know a version to read the
    first four fields and ignore anything a later version appends."""
    ctx = parse_traceparent(
        "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-futurefield")
    assert ctx is not None and ctx.trace_id == CLIENT_TRACE_ID


def test_the_reserved_version_ff_is_malformed():
    """W3C Trace Context reserves `ff` as invalid. This test used to
    assert the opposite, which is how the parser came to continue a trace
    a conforming implementation must discard (review of PR #56)."""
    assert parse_traceparent(
        "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") is None


def test_version_00_with_trailing_data_is_malformed():
    """Version 00 is exactly four fields. A tail on it is not a newer
    version, it is a broken header."""
    assert parse_traceparent(CLIENT_TRACE + "-extra") is None


def test_tracestate_is_carried_verbatim():
    ctx = parse_traceparent(CLIENT_TRACE, "vendor=abc,other=def")
    assert ctx is not None and ctx.tracestate == "vendor=abc,other=def"


def test_an_oversized_tracestate_is_dropped_not_truncated():
    """Truncating vendor state corrupts it; dropping loses nothing this
    project reads."""
    ctx = parse_traceparent(CLIENT_TRACE,
                            "x=" + "y" * (MAX_TRACESTATE_BYTES + 10))
    assert ctx is not None and ctx.tracestate is None


@pytest.mark.parametrize("state", [
    1, ["vendor=abc"], {"vendor": "abc"}, b"vendor=abc", "   ",
])
def test_a_non_string_tracestate_is_dropped_not_fatal(state):
    """The trace is still continued; only the unusable state is dropped."""
    ctx = parse_traceparent(CLIENT_TRACE, state)
    assert ctx is not None and ctx.trace_id == CLIENT_TRACE_ID
    assert ctx.tracestate is None


def test_the_header_round_trips():
    ctx = TraceContext(trace_id=CLIENT_TRACE_ID, span_id="00f067aa0ba902b7")
    assert ctx.traceparent() == CLIENT_TRACE
    assert parse_traceparent(ctx.traceparent()).trace_id == CLIENT_TRACE_ID


def test_a_child_keeps_the_trace_and_takes_a_new_span():
    parent = TraceContext(trace_id=CLIENT_TRACE_ID, span_id="00f067aa0ba902b7")
    child = parent.child()
    assert child.trace_id == parent.trace_id
    assert child.span_id != parent.span_id


# --- binding ---------------------------------------------------------------

def test_nothing_is_bound_outside_a_call():
    assert current_trace() is None
    assert trace_fields() == {}, (
        "an unbound context must contribute no ids; inventing one would "
        "make an audit record look joinable to spans that do not exist")


def test_a_call_without_a_client_header_starts_its_own_trace():
    with trace_call() as ctx:
        assert current_trace() is ctx
        assert len(ctx.trace_id) == 32
    assert current_trace() is None, "the binding is scoped to the call"


def test_a_call_with_a_client_header_continues_that_trace():
    with trace_call(traceparent=CLIENT_TRACE) as ctx:
        assert ctx.trace_id == CLIENT_TRACE_ID


def test_a_locally_started_trace_can_be_pinned_to_a_known_id():
    """So the trace and the audit record it produces carry one id rather
    than two a reader has to join."""
    request_id = "a" * 32
    with trace_call(trace_id=request_id) as ctx:
        assert ctx.trace_id == request_id


def test_an_unusable_pinned_id_falls_back_to_a_generated_one():
    with trace_call(trace_id="not-a-trace-id") as ctx:
        assert len(ctx.trace_id) == 32 and ctx.trace_id != "not-a-trace-id"


def test_bindings_nest_and_unwind():
    with trace_call(traceparent=CLIENT_TRACE) as outer:
        with trace_call() as inner:
            assert current_trace() is inner
            assert inner.trace_id != outer.trace_id
        assert current_trace() is outer


# --- through the server ----------------------------------------------------

async def test_the_audit_record_carries_the_clients_trace():
    ctx = build_ctx()
    server = build_server(ctx, profile="all")
    async with Client(server) as client:
        await client.call_tool(
            "civic.get_code_section", {"citation": "1-500"},
            meta={"traceparent": CLIENT_TRACE})
    record = ctx.audit.records[-1]
    assert record.trace_id == CLIENT_TRACE_ID
    assert record.span_id


async def test_a_call_with_no_client_trace_still_gets_one():
    ctx = build_ctx()
    server = build_server(ctx, profile="all")
    async with Client(server) as client:
        await client.call_tool("civic.get_code_section", {"citation": "1-500"})
    record = ctx.audit.records[-1]
    assert record.trace_id and len(record.trace_id) == 32


async def test_malformed_trace_metadata_cannot_fail_a_call():
    """A caller sending `_meta: {"traceparent": 1}` gets an answer and a
    trace started here, not an AttributeError ahead of the tool (review
    of PR #56)."""
    ctx = build_ctx()
    server = build_server(ctx, profile="all")
    async with Client(server) as client:
        res = await client.call_tool(
            "civic.get_code_section", {"citation": "1-500"},
            meta={"traceparent": 1, "tracestate": ["vendor=abc"]})
    assert res.is_error is False
    record = ctx.audit.records[-1]
    assert record.trace_id and len(record.trace_id) == 32
    assert record.trace_id != CLIENT_TRACE_ID


async def test_a_failed_call_is_traced_too():
    """The call most worth following through its requests is the one that
    went wrong."""
    ctx = build_ctx()
    server = build_server(ctx, profile="all")
    async with Client(server) as client:
        res = await client.call_tool(
            "civic.search_meetings",
            {"jurisdiction": "Richmond City", "start_date": "2026-01-01",
             "end_date": "2029-01-01"},
            meta={"traceparent": CLIENT_TRACE})
    assert res.is_error is True
    record = ctx.audit.records[-1]
    assert record.error and record.trace_id == CLIENT_TRACE_ID


async def test_adapter_log_lines_join_to_the_calls_trace(caplog):
    """The question issue #36 exists to answer: which government requests
    did this tool call make?"""
    ctx = build_ctx()
    server = build_server(ctx, profile="all")
    with caplog.at_level(logging.INFO, logger="commonwealth.adapters"):
        async with Client(server) as client:
            await client.call_tool(
                "civic.search_meetings",
                {"jurisdiction": "Richmond City",
                 "start_date": "2026-09-01", "end_date": "2026-09-30"},
                meta={"traceparent": CLIENT_TRACE})
    lines = [r.getMessage() for r in caplog.records]
    assert any(f"trace={CLIENT_TRACE_ID}" in line for line in lines), (
        f"no adapter log line carried the call's trace: {lines}")
    assert ctx.audit.records[-1].trace_id == CLIENT_TRACE_ID


# --- the boundary ----------------------------------------------------------

def test_upstream_propagation_is_off_by_default(monkeypatch):
    """A government service is not a participant in this trace. Nothing
    is added to what this project puts on the wire to them unless an
    operator says the next hop is theirs."""
    monkeypatch.delenv("COMMONWEALTH_TRACE_UPSTREAM", raising=False)
    assert propagate_upstream() is False


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True),
    ("0", False), ("false", False), ("", False), ("maybe", False),
])
def test_upstream_propagation_is_an_explicit_opt_in(monkeypatch, value,
                                                    expected):
    monkeypatch.setenv("COMMONWEALTH_TRACE_UPSTREAM", value)
    assert propagate_upstream() is expected
