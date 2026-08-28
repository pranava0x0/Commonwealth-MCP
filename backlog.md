# Backlog

Priorities: high / medium / low. Reprioritized as milestones move.

Last reprioritized 2026-08-28 (plan-vs-built review). Milestone 1a's
remaining exit items — the town, the skill, Tier-2 evals, `configure` —
moved into High, where the adopted sequence (ARCHITECTURE.md § 33, § 39)
puts them; they had been sitting in Medium below breadth work.
Statewide-source breadth beyond the proposed-manifest inventory step moved
to Medium until that exit lands.

## High — finish milestone 1a

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
  concluding there's nothing to register — and if that is the conclusion,
  record it with the evidence; a documented absence also closes the item.
- `parcel-zoning-screen` skill (agentskills.io format, capability-ID
  metadata, bench tasks per design/skills.md § 5). The milestone's named
  skill; acceptance criterion § 38.6 requires it benchmarked.
- Tier-2 tool-selection evals (design/bench.md; needs model access and the
  8/12/20-tool sweep from DECISIONS.md 0002). With the skill above, the
  "one evaluated workflow" half of the 1a exit.
- `commonwealth configure <client> --profile --dry-run` (idempotent client
  config writer; the command tree stub exists, the writer doesn't). The
  § 33 CLI list's one unshipped command.
- Fill out the jurisdiction table beyond the 14-row seed. Point-in-polygon
  now resolves any coordinate in Virginia, but only 12 of the 133
  localities have a `va:` id (the 14 rows include the state itself and
  one town), so most points return `unmapped_match` (source knows the
  government, Commonwealth does not). The full 133-row table generates
  from TIGERweb with review; the generator script is the missing piece,
  VGIN's own localities layer (all 133 with FIPS and GNIS, now
  registered) can seed it, and the two then corroborate each other.
  Include the Bedford pair while at it:
  design/jurisdiction-resolution.md § 1 seeds the dissolved-city
  confusion pair and § 3.8 requires its fixture, and no Bedford row
  exists yet. (Merged 2026-08-28 with the Medium "full
  133-jurisdiction table" item — one piece of work split across two
  priorities.)
- Address and ZIP jurisdiction resolution (design/jurisdiction-resolution.md
  § 2's `address` and `zip` rows, § 4). Point-in-polygon shipped
  2026-08-28 and is the hard half; both remaining paths need a registered
  geocoder, and VGIN publishes one (`Geocoding/VGIN_Composite_Locator`, a
  GeocodeServer on the already-allowlisted host). That is a new adapter
  type, not a new layer on the arcgis adapter — GeocodeServer's
  findAddressCandidates contract is different. The terms question is
  smaller than assumed: VGIN's official service-overview PDF states no
  credentials are needed, offers batch geocoding explicitly, and
  publishes no automated-use restriction (verified 2026-08-28,
  RESEARCH.md part 3 § 9). Record that finding in `terms_notes` with
  VGIN's contact (VBMP@VDEM.Virginia.gov) for confirmation — the same
  shape as Richmond's manifest, which records a terms gap instead of
  inventing a terms page. `geo.resolve_location` unblocks at the same
  moment.
- Straddle candidates, not just a warning: design/jurisdiction-resolution.md
  § 3.7 wants a point near a shared border returned as CANDIDATES. Shipped
  behaviour resolves to the containing polygon and warns with the
  neighbour named. Upgrading to candidates + requires_user_choice needs a
  policy call on when a warning becomes a refusal to answer.
- Practice design/source-registry.md § 6.3 as written: the § 6 majors
  (VDOT, DEQ, VDH, Virginia Open Data, eVA, SCC) should each exist as a
  `declared_state: proposed` manifest, not only as the Medium backlog
  line below — the registry's proposed/active split is supposed to
  measure coverage debt, and today the registry holds six manifests, all
  active, zero proposed. Cheap: an `automation_status: unknown` manifest
  validates as inventory without a terms review; it just cannot activate
  (§ 3.2). Flagged 2026-08-28 by the plan-vs-built review.
- License files per DECISIONS.md 0011 (Chosen 2026-08-26, zero of it on
  disk as of 2026-08-28): LICENSE (Apache-2.0), the CC0 + third-party
  exclusions text for `sources/`, CC-BY for docs prose, NOTICE,
  `THIRD_PARTY_DATA.yml`, DCO note in CONTRIBUTING.md. The repo is
  public on GitHub with only a `license = "Apache-2.0"` line in
  pyproject.toml, which covers the Python package metadata and nothing
  else. A project that invites reuse of its registry data currently
  grants nobody the right to reuse it. Cheap and mechanical; flagged
  2026-08-28.
- Pinned-IP httpx transport closing the egress TOCTOU residual (issues.md).

## Medium — developer product and breadth

- More `sources/state/` majors fully onboarded per
  design/source-registry.md § 6's seed list (VDOT road network, DEQ
  environmental sites, VDH) — VGIN statewide parcels and VGIN
  administrative boundaries both shipped 2026-08-28; each new statewide
  source needs its own capability (none of these are parcel.lookup) and
  field verification, same rigor as VGIN. Nearby and already inspected
  live on the same allowlisted host: `VA_Base_Layers/VA_Address_Points`,
  `VA_Building_Footprints`, `VBMP_RCL` (road centerlines),
  `VA_Landmarks`. (Moved from High 2026-08-28: the adopted sequence puts
  new-capability onboarding after the 1a exit; the proposed-manifest
  inventory step stays High.)
- `examples/` runnable CLI demos with `--fixtures` offline mode
  (design/testing-and-demos.md § 3) — distinct from the browser-side
  interactive demos shipped 2026-08-27 (docs/index.html: jurisdiction
  resolver playground, HTTP-exchange view, coverage/warning decoder),
  which read the same recorded run rather than executing keyless live.
- Reconciliation-audit job: replay committed fixtures against live services
  on a schedule, diff, file drift (`docs/audits/upstream-<date>.md`).
- Start the § 38.13-17 metric log the acceptance criteria say to track
  "from the first milestone" (ARCHITECTURE.md § 38): per source onboarded,
  time spent and whether server/CLI code had to change. The record so far,
  reconstructed from RUNLOG: Richmond needed an adapter extension
  (per-layer service_url), VGIN parcels and Charles City each surfaced a
  CLI single-source assumption, boundaries needed three adapter features —
  0 of the last 5 sources landed with zero code change. Expected while
  single-source assumptions are still being found; the metric exists to
  show whether that count falls toward zero. A table appended per
  onboarding (RUNLOG or `docs/audits/`) is enough.

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
  LIS's own JSON API — `lis.virginia.gov/developers` (bills, members,
  committees; 40+ endpoints, JWT Bearer auth; the public pages document
  no XML — verified 2026-08-28, RESEARCH.md part 3 § 9) — which requires
  registering at `lis.virginia.gov/apiregistration` for an API key
  (`access.mode: api_key`, already a valid value in the schema's `mode`
  field — no manifest-schema gap, but no adapter yet attaches an API key
  to outbound requests, and getting a key is a registration step for
  whoever builds this, not something to automate around). A full-text
  `search_law` over the Code of Virginia is also still open — the site's
  own search feature (`searchCoV.js`) wasn't reverse-engineered; worth
  checking whether it needs a key or is public like the section pages.
