"""The `none` adapter: a manifest that is inventory, not an endpoint.

design/source-registry.md § 6.3 says every "we should cover X someday" idea
becomes a `proposed` manifest rather than a backlog line, so the registry's
proposed/active split measures coverage debt for free. Those manifests have
no service to describe — sometimes because nobody has looked for one yet,
sometimes (VDH) because the search ran and found none.

`adapter.type: none` is how that is said out loud. It registers a params
model that accepts nothing, so a proposed manifest cannot smuggle a
half-filled `service_url` past validation and read as almost-wired. There
is no adapter class here on purpose: the activation gates in
`core/registry.validate_manifest` refuse `declared_state: active` for this
type, so nothing can ever try to query one.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..core.registry import register_adapter_params

# The one field a proposed manifest may carry: where a human should start
# looking. It is a document or portal URL, never something an adapter reads
# — nothing in this codebase fetches it.
class InventoryOnlyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discovery_url: str | None = None


register_adapter_params("none", InventoryOnlyParams)
