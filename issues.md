# Issues

Living audit trail (base-files convention): date, area, description, root
cause, status.

## Open

- **2026-08-27 · egress · DNS resolve-to-connect window (TOCTOU residual).**
  `EgressPolicy` resolves and checks addresses immediately before the
  request, but httpx re-resolves at connect, so a rebinding attacker with
  sub-second TTLs has a theoretical window. Planned fix: a pinned-IP httpx
  transport so the checked address is the connected address. Documented in
  `core/egress.py`; the policy tests cover every rule at the validation
  layer. Severity: low for V1 (read-only, registered .gov hosts only).
- **2026-08-27 · adapters · politeness semaphores are per-process.**
  `PER_HOST_CONCURRENCY` caps concurrency inside one process; several
  processes (CLI + server) don't share a budget. Acceptable at V1 scale;
  revisit with hosting.
- **2026-08-27 · geo · zoning-by-PIN uses the first parcel polygon when a
  PIN matches several.** The response says so (`parcel_note`) and lists the
  count, but a multi-polygon parcel's zoning could be incomplete. Fix
  candidate: intersect each polygon (bounded) and union the districts.
- **2026-08-27 · registry · `search_sources` text match is naive substring**
  over id+name. Fine for 1 manifest; needs word-ish matching before the
  registry grows.
- **2026-08-27 · sources · zoning health floor (5,000) calibrated from a
  single live observation** (6,440 on 2026-08-27). Re-check after the next
  few probes before trusting the floor's headroom.

## Fixed (this session, pre-first-commit)

- **2026-08-28 · cli · `sources sample` assumed every arcgis manifest has
  both a `parcels` and a `zoning` layer.** Registering VGIN's statewide
  parcels-only source (`va-vgin-statewide-parcels`) made this concrete:
  `commonwealth sources sample` crashed with `InvalidQuery: manifest ...
  declares no layer 'zoning'`. Root cause: code bug (same class as the
  `doctor --live` hardcoding below — single-source assumptions baked in
  before a second source shape existed to catch them). Fix: skip the
  zoning-dependent sampling steps when the manifest declares no `zoning`
  layer (`src/commonwealth/cli/__main__.py`).
- **2026-08-28 · cli · `doctor --live` only ever probed the Fairfax
  manifest.** The live-probe branch hardcoded
  `ctx.sources.get("va-fairfax-parcels-zoning")`; adding Richmond as a
  second source would have left it permanently unprobed with no error —
  `doctor` would keep reporting 0 problems while silently checking half
  the registry. Root cause: code bug (single-source assumption baked in
  before a second source existed to catch it). Fix: iterate
  `ctx.sources.manifests.values()` and every layer each declares
  (`src/commonwealth/cli/__main__.py`). No regression test added yet —
  candidate: a `doctor --live` test asserting the printed line count
  scales with the number of registered arcgis layers.

- **2026-08-27 · envelope · wire/schema mismatch.** The serializer emitted
  `_execution` while the schema declared `execution`; the SDK's strict
  client-side validation caught it immediately. Root cause: code bug
  (schema not describing the wire). Fix: `__get_pydantic_json_schema__`
  renames the property; regression: `test_schema_describes_the_wire_not_the_model`.
- **2026-08-27 · servers · typed errors reached the model as generic
  "Error executing tool".** The SDK treats unknown exceptions as crashes.
  Root cause: code bug (missing translation to the SDK's `ToolError`
  pass-through). Fix in `servers/build.py`; regressions:
  `test_invalid_args_surface_as_tool_error`,
  `test_search_sources_unknown_capability_is_typed_error`.
- **2026-08-27 · servers · `from __future__ import annotations` left tool
  hints as strings the SDK couldn't resolve**, so output schemas silently
  failed to generate (warning-only). Fix: `eval_str` signature resolution in
  the binding; regression: `test_every_tool_has_output_schema_and_stable_order`.
- **2026-08-27 · sources · one `min_features` floor applied to both layers**,
  flagging healthy zoning (6,440) against the parcel floor (300,000). Root
  cause: data bug (manifest shape too coarse). Fix: per-layer floors +
  adapter support; verified by live probe.
