"""Commonwealth-MCP: MCP servers for Virginia public data.

Layout (../../design/architecture.md decision 0001, 0003, 0015):
- core/     framework-free contracts and logic; imports neither mcp nor cli
- adapters/ protocol clients (ArcGIS first), egress-checked, read-only
- servers/  thin MCP bindings over core tool functions
- cli/      contributor/debug surface, not a supported public API
"""

__version__ = "0.1.0.dev0"
