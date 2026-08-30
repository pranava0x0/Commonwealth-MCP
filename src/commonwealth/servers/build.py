"""Assemble the MCPServer from domain tool registries.

One process, domain packages, toolset profiles (../../../design/architecture.md decision 0001, 0002).
Registration order is deterministic: profile order, then registry order.
Every tool is read-only and annotated as such. The deprecation-alias
mechanism registers alias names that call the same handler; the table is
empty until the first rename (design/domain-servers.md § 1.6).
"""
from __future__ import annotations

import inspect
import time
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ..core.audit import error_record, record_from_envelope
from ..core.errors import CommonwealthError
from ..core.toolreg import (DEPRECATED_TOOL_ALIASES, ToolSpec, expand_profile)
from ..domains.civic import CIVIC_TOOLS
from ..domains.geo import GEO_TOOLS
from ..domains.registry import REGISTRY_TOOLS
from ..runtime import RuntimeContext

SERVER_INSTRUCTIONS = (
    "Commonwealth-MCP serves Virginia public-data queries with provenance. "
    "Read coverage before concluding anything: result='empty' with "
    "registry='covered' means the searched systems hold no record; "
    "registry='none' means Commonwealth has no source for that place and "
    "the record may still exist. When a result sets requires_user_choice, "
    "present the candidates to the user and do not pick one. Zoning answers "
    "are screening evidence, never legal determinations."
)


def _bind(spec: ToolSpec, ctx: RuntimeContext):
    async def wrapper(**kwargs: Any):
        started = time.monotonic()
        try:
            envelope = await spec.fn(ctx, **kwargs)
        except CommonwealthError as err:
            ctx.audit.append(error_record(
                tool=spec.name, args=kwargs, error_code=err.code,
                duration_ms=int((time.monotonic() - started) * 1000),
                server=ctx.server_name, server_version=ctx.server_version,
                registry_revision=ctx.sources.revision,
                sensitive=ctx.has_sensitive_sources()))
            # Typed errors are anticipated failures whose message is written
            # FOR the model (design/provenance-envelope.md § 7); ToolError is
            # the SDK's pass-through channel for exactly that.
            raise ToolError(err.model_message()) from err
        sensitive = any(
            ctx.classification_of(s.source_id) == "sensitive_public"
            for s in envelope.provenance)
        ctx.audit.append(record_from_envelope(
            spec.name, kwargs, envelope,
            duration_ms=int((time.monotonic() - started) * 1000),
            sensitive=sensitive))
        return envelope

    # Domain modules use `from __future__ import annotations`, so hints are
    # strings the SDK cannot resolve from its own module. eval_str resolves
    # them to real types here; a contract test asserts every bound tool got
    # an output schema, so a regression cannot slip through as a warning.
    sig = inspect.signature(spec.fn, eval_str=True)
    params = [p for name, p in sig.parameters.items() if name != "ctx"]
    wrapper.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        params, return_annotation=sig.return_annotation)
    wrapper.__annotations__ = {
        name: p.annotation for name, p in sig.parameters.items()
        if name != "ctx"} | {"return": sig.return_annotation}
    wrapper.__name__ = spec.name.replace(".", "_")
    wrapper.__doc__ = spec.description
    return wrapper


def registries():
    return {"registry": REGISTRY_TOOLS, "geo": GEO_TOOLS, "civic": CIVIC_TOOLS}


def build_server(ctx: RuntimeContext, profile: str = "default") -> MCPServer:
    specs = expand_profile(profile, registries())
    server = MCPServer(name=ctx.server_name, version=ctx.server_version,
                       instructions=SERVER_INSTRUCTIONS)
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                  open_world_hint=True)
    registered: dict[str, ToolSpec] = {}
    for spec in specs:
        server.tool(name=spec.name, description=spec.description,
                    annotations=annotations)(_bind(spec, ctx))
        registered[spec.name] = spec

    for old_name, current in DEPRECATED_TOOL_ALIASES.items():
        spec = registered.get(current)
        if spec is None:
            continue  # alias targets a tool outside this profile
        server.tool(
            name=old_name,
            description=f"Deprecated alias of {current}. " + spec.description,
            annotations=annotations)(_bind(spec, ctx))
    return server
