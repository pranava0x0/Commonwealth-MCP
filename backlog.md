# Backlog

Priorities: high / medium / low. Reprioritized as milestones move.

## High — geo vertical

- More `sources/state/` majors per design/source-registry.md § 6's seed
  list (VDOT road network, DEQ environmental sites, VDH) — VGIN statewide
  parcels and VGIN administrative boundaries both shipped 2026-08-28; each
  new statewide source needs its own capability (none of these are
  parcel.lookup) and field verification, same rigor as VGIN. Nearby and
  already inspected live on the same allowlisted host:
  `VA_Base_Layers/VA_Address_Points`, `VA_Building_Footprints`,
  `VBMP_RCL` (road centerlines), `VA_Landmarks`.
- Fill out the jurisdiction table beyond the 14-row seed. Point-in-polygon
  now resolves any coordinate in Virginia, but only 14 of the 133
  localities have a `va:` id, so most points return `unmapped_match`
  (source knows the government, Commonwealth does not). VGIN's own
  localities layer carries all 133 with FIPS and GNIS, so it can seed the
  generator the "full 133-jurisdiction table" item below still needs.
- One incorporated town through the same workflow (the schema-honesty
  forcing set from design/source-registry.md § 6) — the rural-county half
  shipped 2026-08-28 (Charles City County: a genuinely minimal public
  view, 2 fields, no zoning layer, exactly the kind of thin real source
  the forcing set was meant to surface). Vienna is the only seeded town
  jurisdiction; a live search 2026-08-28 found only its zoning-map viewer
  app (an ArcGIS web app, not a queryable REST endpoint) — no separate
  parcels/zoning FeatureServer surfaced. Likely genuinely thin: small
  towns commonly ride on their county's own assessor GIS rather than
  publishing one. Worth one more targeted check (Vienna's own GIS/IT
  contact, or the ArcGIS Online org behind that viewer app) before
  concluding there's nothing to register.
- Address and ZIP jurisdiction resolution (design/jurisdiction-resolution.md
  § 2's `address` and `zip` rows, § 4). Point-in-polygon shipped
  2026-08-28 and is the hard half; both remaining paths need a registered
  geocoder, and VGIN publishes one (`Geocoding/VGIN_Composite_Locator`, a
  GeocodeServer on the already-allowlisted host). That is a new adapter
  type, not a new layer on the arcgis adapter — GeocodeServer's
  findAddressCandidates contract is different — plus a terms review, since
  geocoder terms are where "no storing/deriving" clauses usually live.
  `geo.resolve_location` unblocks at the same moment.
- Straddle candidates, not just a warning: design/jurisdiction-resolution.md
  § 3.7 wants a point near a shared border returned as CANDIDATES. Shipped
  behaviour resolves to the containing polygon and warns with the
  neighbour named. Upgrading to candidates + requires_user_choice needs a
  policy call on when a warning becomes a refusal to answer.
- Pinned-IP httpx transport closing the egress TOCTOU residual (issues.md).

## Medium — developer product

- `commonwealth configure <client> --profile --dry-run` (idempotent client
  config writer; the command tree stub exists, the writer doesn't).
- `parcel-zoning-screen` skill (agentskills.io format, capability-ID
  metadata, bench tasks per design/skills.md § 5).
- Tier-2 tool-selection evals (design/bench.md; needs model access and the
  8/12/20-tool sweep from DECISIONS.md 0002).
- `examples/` runnable CLI demos with `--fixtures` offline mode
  (design/testing-and-demos.md § 3) — distinct from the browser-side
  interactive demos shipped 2026-08-27 (docs/index.html: jurisdiction
  resolver playground, HTTP-exchange view, coverage/warning decoder),
  which read the same recorded run rather than executing keyless live.
- Reconciliation-audit job: replay committed fixtures against live services
  on a schedule, diff, file drift (`docs/audits/upstream-<date>.md`).
- Full 133-jurisdiction table generated from TIGERweb with review
  (14-row pilot seed shipped; the generator script is the missing piece).
  VGIN's boundary layer is now a registered second opinion for every FIPS
  and name in it.

## Low / later milestones

- Result-resource store per DECISIONS.md 0013 (envelope `resources` is
  structurally present, always empty today). Now has a concrete first
  customer: `geo.find_boundaries` generalizes geometry to 0.0002 degrees
  to fit inline, and the unsimplified polygon has nowhere to live until
  this exists. The tool says so rather than pretending the simplified
  rings are the boundary.
- Signed pagination cursors (same record).
- Multi-page ArcGIS pagination (today: single page + an explicit
  `pagination: truncated` via `exceededTransferLimit`).
- `GOVERNANCE.md` / `CONTRIBUTING.md` § security additions / CODEOWNERS
  before the first external manifest PR (design/security-and-data-handling.md § 5).
- OTel trace-context propagation (design spec § 23 note).
- Civic vertical (milestone 1b): rest of the default toolset —
  `civic.search_legislation`, `civic.get_bill`, `civic.search_meetings`
  (design/domain-servers.md § 4). `civic.get_code_section` (direct
  citation lookup, not full-text search) shipped 2026-08-28 against the
  public law.lis.virginia.gov HTML pages, no key needed. The rest needs
  LIS's own JSON/XML API — `lis.virginia.gov/developers` (bills, members,
  committees; 40+ APIs) — which requires registering for an API key
  (`access.mode: api_key`, already a valid value in the schema's `mode`
  field — no manifest-schema gap, but no adapter yet attaches an API key
  to outbound requests, and getting a key is a registration step for
  whoever builds this, not something to automate around). A full-text
  `search_law` over the Code of Virginia is also still open — the site's
  own search feature (`searchCoV.js`) wasn't reverse-engineered; worth
  checking whether it needs a key or is public like the section pages.
