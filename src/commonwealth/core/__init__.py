"""Commonwealth Core: framework-free contracts and logic.

This package must import neither `mcp` nor anything under
`commonwealth.servers`/`commonwealth.cli` — a test enforces it. That
discipline (../../../design/architecture.md decision 0003, retained under 0015) is what keeps a future
public-library promotion additive.
"""
