# Spec: Government Source Registry

**Plugs into:** architecture.md § 11 (Government Source Registry), § 20 (Legal/Terms), § 28 (Source Selection)
**Status:** Draft for review. Manifest schema v1 freezes when the first three localities are onboarded and have forced the schema to be accurate.
**Why this exists:** The registry is the project's most durable asset: a machine-readable inventory of what Virginia public systems exist, who publishes them, how to access them lawfully, and how they map into capabilities. Everything else (adapters, tools, skills) consumes it. If the registry is right, adding locality #4 through #133 is data entry plus review; if it is wrong, every locality is a software project.

---

## 1. Manifest schema v1

One YAML file per source. Directory layout groups by publisher level: `sources/state/`, `sources/local/<jurisdiction-slug>/`, `sources/regional/`, `sources/federal-federated/`.

```yaml
# sources/local/fairfax-county/zoning.yaml
id: va-fairfax-zoning
name: Fairfax County Zoning Districts
jurisdiction: va:fairfax-county

publisher:
  agency: Fairfax County Department of Planning and Development
  authority_level: primary          # primary | official_secondary | official_derived | third_party | unverified

domains: [geo, planning]

capabilities:
  - id: zoning.lookup
    tool_hint: geo.find_zoning
  - id: zoning.spatial_intersection

adapter:
  type: arcgis                      # must name a registered adapter
  service_url: https://www.fairfaxcounty.gov/.../FeatureServer
  layers:
    zoning:
      layer_id: 4
      field_mapping:
        district: ZONING
        district_description: ZONING_DESC
        object_id: OBJECTID
      geometry: polygon
      crs: EPSG:3857

access:
  mode: anonymous                   # anonymous | api_key | oauth | restricted
  automation_status: public_api     # see § 3
  terms_url: https://www.fairfaxcounty.gov/maps/terms
  terms_notes: >
    County GIS terms permit use of published services; no bulk-download
    restriction noted as of review date.
  terms_reviewed_at: 2026-08-26
  data_classification: open         # open | sensitive_public | restricted (design/security-and-data-handling.md § 3)
  # sensitive_public additionally requires:
  #   exposure_allowlist: [field, ...]
  #   classification_reviewed_by: <handle>
  #   classification_reviewed_at: <date>

freshness:
  expected_cadence: daily
  cadence_source: stated            # stated (publisher says) | observed (we measured) | unknown
  ttl_hint_seconds: 86400           # feeds the adapter response cache and ttlMs on result RESOURCES
                                    # (protocol cache hints do not attach to tools/call results)

coverage:
  geography: va:fairfax-county
  temporal: current                 # current | range | snapshots
  known_limitations:
    - Pending rezonings appear only after adoption.

authority_notes: >
  GIS layer is a screening representation. The adopted zoning ordinance and
  official zoning map govern; confirm before legal reliance.

health:
  probe: arcgis_layer_info          # adapter-defined probe type
  expect:
    min_features: 1000              # sanity floor; fewer means the layer moved

lifecycle:
  declared_state: active            # proposed | active | retired — reviewed, lives in VCS
  added: 2026-08-26
  last_verified: 2026-08-26
  verified_by: <contributor handle>
```

Live health is deliberately NOT a manifest field. `operational_state` (`healthy | impaired | unavailable | unknown`) lives in runtime monitoring storage, written by scheduled probes and read by source selection; a county server's Tuesday outage must not generate a Wednesday PR (2026-08-26 review § 2.5). The two states compose at query time: selectable = `declared_state: active` AND `operational_state` not `unavailable`.

Schema rules:

1. **Every field above except `layers.*.field_mapping` extras is required.** A manifest missing `terms_url`/`terms_notes` does not validate; "unknown" is written explicitly (`automation_status: unknown`) and blocks activation (§ 3).
2. **`capabilities[].id` comes from a controlled vocabulary** (`capabilities.yaml` in the registry root). Adding a capability ID is a reviewed change; this is what keeps source-to-tool routing coherent, and every routing table iterates the vocabulary file rather than restating it.
3. **`adapter.type` must name a registered adapter**; the manifest validator loads the adapter's own parameter schema and validates the block against it (an `arcgis` block validates layer IDs and field mappings; a `socrata` block validates dataset IDs and SoQL field names).
4. **Field mappings map source fields to canonical fields**, and the canonical field names come from the entity schemas in Commonwealth Core. The validator rejects a mapping onto a canonical field that does not exist. This is single-source-of-truth discipline applied to data plumbing.
5. **No secrets in manifests, ever.** `access.mode: api_key` names an env var (`credential_ref: VDOT_API_KEY`), never a value.

## 2. Source selection metadata

Selection follows architecture.md decision 0005 as **Chosen (architect override, 2026-08-26)**: no central ranking and no derived "primary." For a (jurisdiction, capability) request, selection picks the **top two** candidate sources — filtered to selectable ones, ordered by `authority_level` then freshness for the *which two* question only — queries both, and surfaces both results. The registry supplies every input:

- Selection inputs come only from manifest fields plus live operational state; nothing hard-codes "Fairfax first," and nothing anywhere reconciles two official answers into one.
- `operational_state: unavailable` (probe failing > N hours, held in runtime storage) drops a source from default selection and surfaces it in `coverage.source_failures` when it would have been used; `impaired` keeps it selectable with a warning. Unavailable is not retired: the agent learns the source exists and is down, and no manifest edit occurs.

## 3. Terms, automation status, and the activation gate

`automation_status` vocabulary, unchanged from architecture.md § 20: `permitted | public_api | public_download | manual_review_required | restricted | do_not_automate | unknown`.

Hard rules enforced by the validator and CI, not by convention:

1. Only `permitted`, `public_api`, `public_download` sources can be `declared_state: active`.
2. `manual_review_required`, `restricted`, `unknown` sources validate but cannot activate; they exist as inventory ("we know this system exists; here is why it is not wired up"), which is itself valuable research output.
3. `do_not_automate` requires a `terms_notes` explanation and pins the source out of Explorer reach too, not just out of the domain tools.
4. `data_classification: sensitive_public` requires the field-level `exposure_allowlist` plus a named reviewer and date (design/security-and-data-handling.md § 3 carries the handling rules — public officials' names on votes: `open`; license holders' home addresses: allowlisted out). `restricted` cannot activate. Reviewed at Gate B.
5. `terms_reviewed_at` older than 12 months flags the manifest in CI as needing re-review; the gate warns, a human decides. Terms drift; the registry must not silently assert year-old permission as current, and a warning that fires on time alone stays advisory per house CI rules.

## 4. Contribution workflow

The design-spec § 11.3 eight-step flow, made concrete:

```text
commonwealth source scaffold arcgis          # writes a template manifest with TODOs
# contributor fills in service_url, mappings, terms fields
commonwealth source validate <file>          # schema + adapter-param + capability-vocab checks
commonwealth source probe <file>             # live: health probe, field existence, row counts
commonwealth source sample <file>            # runs each declared capability once, prints envelopes
# contributor commits manifest + the recorded fixture from `sample`
# PR review checklist (enforced as a PR template):
#   terms fields human-verified against the linked page
#   authority_level justified in the PR body
#   fixture reviewed for PII surprises
#   capability mapping sanity (does zoning.lookup really return districts?)
```

`probe` and `sample` write their outputs under `tests/fixtures/sources/<id>/` so every merged source lands with a replayable fixture on day one. The recorded fixture is the contract test; a later schema change by the publisher fails the replay comparison loudly (`SourceSchemaChanged`), which is the drift alarm the health probe's `min_features` floor cannot provide. Fixtures are third-party payloads: each carries source and rights metadata and sits outside the repo's blanket data license (architecture.md decision 0011). The per-fixture rights block is built and repo-health-tested; the `THIRD_PARTY_DATA.yml` inventory, NOTICE, and the license files themselves are not yet written (noted 2026-08-28; backlog High).

External contributions have prerequisites beyond tooling: GOVERNANCE.md, CONTRIBUTING.md, a project SECURITY.md, and CODEOWNERS routing `sources/**` to named source reviewers exist before the first outside manifest PR is accepted (design/security-and-data-handling.md § 5).

## 5. What the registry is not

- Not the MCP catalog: which *servers* exist, their endpoints, and tenancy live in the Hub catalog (design/hub-catalog.md). A registry row can exist with no server exposing it yet.
- Not a data warehouse: manifests describe access, they never embed data. Retention questions are design/0006.
- Not national: schema fields avoid Virginia-isms (nothing hard-codes independent cities), but the instance data is Virginia's. Gate G governs generalization.

## 6. Inventory-first working style

The registry is also the project's research notebook made executable. Phase 0/1 sequencing:

1. Seed `sources/state/` with the known majors (VGIN, Virginia Open Data, LIS, Virginia Law, VDOT, DEQ, VDH, eVA/procurement, SCC) as manifests even where `status: proposed`, terms not yet reviewed.
2. Seed four localities through the full workflow including terms review: Fairfax County, Richmond City, one rural county, and one incorporated town inside a county (revised per the 2026-08-26 review — the rural and nested-town cases exercise the jurisdiction traps and thin-data reality that two big suburban counties cannot; Loudoun follows right after). These force the schema to be honest before it freezes.
3. Every "we should cover X someday" idea becomes a `proposed` manifest instead of a backlog line; the registry's proposed/active split then measures coverage debt for free (`commonwealth sources stats`).

## 7. Testing hooks

- Schema validation over every manifest in CI (`commonwealth source validate --all`), including the activation-gate rules of § 3, with the checked-manifest count printed so a glob miss is visible.
- Fixture replay per active source (see § 4); replay failures report as `SourceSchemaChanged` with the failing fields named.
- Vocabulary derivation tests: capability routing tables, docs tables, and the CLI's `sources search` index all iterate the manifest directory; a hand-typed mirror of the source list anywhere in the tree is a test failure by design.
- A liveness budget: `probe --all` runs on a schedule, not in PR CI (network flake must not gate merges); its output writes `operational_state` to runtime monitoring storage directly — no PRs for outages. Only durable findings (a source gone for weeks, a schema change) become PRs, as `declared_state` or manifest edits, because those are reviewed judgments rather than weather.
