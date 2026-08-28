# Issues

Living audit trail (base-files convention): date, area, description, root
cause, status.

## Open

- **2026-08-28 · envelope · wire emits singular `evidence_ref`; the
  contract says `evidence_refs` array.** design/provenance-envelope.md § 2
  and ARCHITECTURE.md § 10.1 (both from review round 2 § 2.2, a blocking
  contract correction) require every material record to carry an
  `evidence_refs` list; `geo.py`/`civic.py` emit a single string and the
  contract tests pin that shape. Root cause: implementation predated
  re-reading the revised spec, and the contract test was written from the
  code. The multi-polygon-PIN zoning issue below is a live case wanting
  several refs on one record. Recommendation: migrate to the array now,
  while the wire has zero external consumers; spec § 2 carries the
  divergence note. The architect decides.
- **2026-08-28 · egress · rules 6–7 have no refusal fixtures, and no
  decompression-expansion limit exists.** DECISIONS.md 0014 froze seven
  baseline rules "each with a fixture-tested known-bad request";
  tests/core/test_egress.py covers rules 1–5. Response-size capping
  exists post-download (`MAX_RESPONSE_BYTES` in adapters/base.py) but has
  no test, no streaming cutoff, and no expansion-ratio guard distinct
  from the byte cap; per-host concurrency and retry budgets likewise run
  untested. Root cause: the fixture suite was built rule-by-rule and
  stopped early. Severity: low at V1 scale (registered .gov hosts only),
  but the 0014 Choice text overclaims until these exist.
- **2026-08-28 · toolsets · `default` includes `registry.resolve_jurisdiction`
  via a `discovery-min` toolset; DECISIONS.md 0001's Choice says registry
  tools ship outside `default`.** The refinement is defensible (every
  walk starts with resolution; the meta tools stay out) and is now
  documented in design/domain-servers.md § 1.7, but it amends a Chosen
  record's letter and nothing recorded it. Needs the architect's
  ratification — either a dated amendment note in 0001 or a revert.
- **2026-08-28 · toolsets · DECISIONS.md 0002's tool budget is only
  half enforced, and `default` sits under its floor.**
  `core/toolreg.expand_profile()` raises above `PROFILE_HARD_CEILING = 20`
  and nothing else. `PROFILE_DEFAULT_CEILING = 12` is defined but never
  read at runtime — only `tests/test_repo_health.py` asserts it, so an
  oversized `default` fails CI rather than startup. The 8-tool floor 0002
  chose has no check anywhere, and `default` currently expands to five
  tools (`registry.resolve_jurisdiction`, `geo.find_parcel`,
  `geo.find_zoning`, `geo.find_boundaries`, `civic.get_code_section`).
  Root cause: the ceiling was implemented, the band was not; the floor is
  also genuinely unmeetable today, since the domains that would fill it
  (the rest of civic, the statewide-source capabilities) are unbuilt — a
  hard floor check would refuse to start the server that exists. Found
  2026-08-28 by review of the plan-vs-built pass, which had itself claimed
  the module "enforces" both numbers; ARCHITECTURE.md § 15 now states what
  is actually enforced. Two ways to close it, and the choice is the
  architect's: enforce the default ceiling at expansion and add the floor
  as a warning-at-startup rather than a refusal, or amend 0002 with a
  dated note that the floor is an aspiration for a filled-out toolset and
  the enforced contract is the 20-tool ceiling.
- **2026-08-28 · docs-in-code · two stale strings.** `core/envelope.py`'s
  module docstring lists `conflict` among envelope fields that drop when
  empty — no such field exists (`extra="forbid"`; the shipped block is
  `data["comparison"]`). `adapters/virginia_law.py` cites "design § 27:
  never guess" — the never-guess rule is provenance-envelope § 2 /
  ARCHITECTURE § 10.1 (locators), not § 27. Both one-line fixes next time
  those files are open.

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
