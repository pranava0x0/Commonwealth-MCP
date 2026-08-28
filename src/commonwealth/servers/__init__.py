"""MCP bindings: thin layer mapping domain tool registries onto MCPServer.
The only package (besides cli's serve command) that imports `mcp`."""

from .build import build_server  # noqa: F401
