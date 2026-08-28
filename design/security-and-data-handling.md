# Spec: Security and Data Handling

**Plugs into:** Design Spec § 19 (Authentication and Security), § 20 (Legal/Terms), § 23 (Observability); DECISIONS.md 0014 fixes the choices this spec applies.
**Status:** Draft for review. Added after the 2026-08-26 architecture review (§ 3.1-3.2), which correctly called the prior posture asserted-but-undefined. base-files/SECURITY.md remains the house template; this document is the Commonwealth-specific contract.

---

## 1. Threat model (V1: public, read-only, anonymous)

Assets: the integrity of answers (an agent trusting a wrong or planted result), the availability and goodwill of government endpoints (Commonwealth must never be the reason a county rate-limits everyone), users' query privacy, and the project's authority reputation.

Adversaries and the failures they produce:

| Threat | Vector | Primary defenses |
|---|---|---|
| Indirect prompt injection | Adversarial text inside government-published records (agendas, comments, filings) | Results are data by contract; no tool output is ever executed or treated as instruction; injection-trap bench tasks (design/bench.md § 2); envelope carries no model-directed imperatives |
| SSRF / egress abuse | A manifest, redirect, or DNS answer steering requests at internal or third-party targets | Egress baseline (§ 2), registry-bound outbound only, manifest review as the grant review |
| Supply-chain | Malicious or compromised dependencies; typosquats | Pinned deps, lockfile review per base-files/SECURITY.md; no vendored unofficial-API clients (DECISIONS.md 0011) |
| Tool-contract tampering ("rug pull") | A modified server presenting altered tool semantics | Published schemas + toolsnaps make drift diffable; registry namespace verification for published artifacts |
| Data misuse via aggregation | Individually-public fields combined into profiles (owner names × permits × licenses) | Classification + field allowlists (§ 3); no cross-source person-keyed joins in V1 (DECISIONS.md 0010 scope) |
| Resource abuse of upstreams | Runaway agents hammering county servers | Politeness budgets per host (design/adapters.md § 1.5), probe cadence caps, response limits |
| Log/cache leakage | Sensitive values persisted in operational exhaust | Structural log minimization (§ 4), classification-aware caching |

Out of V1 scope by construction, each re-opened at its named gate: credential theft (no credentials exist until Gate D), write abuse (no writes until Gate F), tenant isolation (no tenants until Phase 3).

## 2. Egress policy

The enforceable definition of "no arbitrary outbound." Full rule list and rationale in DECISIONS.md 0014 § 1; normative summary:

1. Outbound requests originate only from adapter code paths parameterized by an active registered manifest. There is no generic fetch anywhere in the tool surface.
2. HTTPS by default; `insecure_transport: true` is a reviewed manifest flag that surfaces as a provenance warning.
3. Host allowlist per manifest; IP literals refused; private/loopback/link-local/metadata ranges refused with DNS re-checked at connect; redirects capped at 3, same-host-set only, credentials stripped cross-host.
4. Response-size and decompression caps; per-host concurrency and retry budgets from the manifest.
5. Every rule ships with a known-bad fixture that must be refused (design/testing-and-demos.md § 1 security tier) — an egress rule without its refusal test is prose, not policy.

## 3. Data classification

Per DECISIONS.md 0014 § 2 (recommendation A): every manifest declares `data_classification: open | sensitive_public | restricted`, replacing the earlier `pii_risk` field.

- `open`: no field restrictions. The default for GIS layers, legislation, budgets.
- `sensitive_public`: lawful to publish, unwise to fire-hose. Requires in the manifest: a field-level `exposure_allowlist` (fields not listed never leave the adapter), `raw_retention: forbidden` (no `include_raw`, no stored payload beyond the response cache under the same allowlist), a named reviewer and review date. Typical: parcel ownership names, professional-license holder details, campaign-finance individual donors.
- `restricted`: cannot activate (matches `automation_status` restrictions; the two fields are independent checks that both must pass).

Display rule: tools serving `sensitive_public` results add a `warnings` entry naming the classification, so downstream consumers inherit the caution with the data.

## 4. Logging and cache minimization

- Observability records for `sensitive_public` sources carry tool, source ID, timing, counts, and error class — never argument values, never result fields. `open` sources log arguments (they are things like parcel IDs and bill numbers, and they make debugging possible).
- Caches (adapter TTL cache, result store per DECISIONS.md 0013) store `sensitive_public` responses post-allowlist: dropped fields are dropped before storage, not redacted after.
- No IP-level user analytics; request IDs are random, not derived from callers. Query privacy is part of the civic offer.

## 5. Governance prerequisites for external contributions

Before the first external source-manifest PR is accepted (per review § 3.4): `GOVERNANCE.md` (who maintains the capability vocabulary, who reviews sources/terms/classifications, who owns security response, how a source is deprecated or transferred), `CONTRIBUTING.md`, a project `SECURITY.md` superseding the house template for reporters, CODEOWNERS routing `sources/**` to source reviewers, and DCO sign-off on contributions (DECISIONS.md 0011). These are files with named humans in them, so they are written at implementation time, not drafted here.

## 6. What this spec deliberately does not cover

Authentication design (Gate D re-opens with EMA/CIMD per the design spec § 19.3 note), write-path security (Gate F), and multi-tenant isolation (Phase 3) — each gets its threat-model revision when its gate opens, and building their machinery now would be speculative surface.
