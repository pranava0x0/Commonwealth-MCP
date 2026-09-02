# Governance

Who decides what, and how a decision gets changed. Written 2026-09-01,
before the first source manifest from outside the project
(design/security-and-data-handling.md § 5).

## Who

One maintainer today: [@pranava0x0](https://github.com/pranava0x0). Every
role below is theirs until someone else is named here in a pull request.
Saying so plainly is more useful to a contributor than a table of empty
roles, and it sets the expectation for how fast a review comes back.

| Role | Holder | What it covers |
|---|---|---|
| Project maintainer | @pranava0x0 | Merges, releases, and anything not listed below |
| Capability vocabulary | @pranava0x0 | `sources/capabilities.yaml`: adding a capability, renaming one, retiring one |
| Source review | @pranava0x0 | Every manifest under `sources/**`, its terms fields, and its authority level |
| Data classification | @pranava0x0 | Whether a source is `open` or `sensitive_public`, per design/security-and-data-handling.md § 3 |
| Security response | @pranava0x0 | Reports arriving through [SECURITY.md](SECURITY.md) |
| Architecture decisions | @pranava0x0 | Part 2 of design/architecture.md |

`CODEOWNERS` routes the review requests, so it names the same people. The
two files disagreeing is a bug in whichever was edited last.

## Reviewing a source manifest

A manifest names a government service and says what its publisher's terms
allow. Reviewing one means checking those two claims, not reading code.

The checklist is design/source-registry.md § 4, and a reviewer works
through it in order:

1. **Terms fields were read by a human against the linked page.** Not
   inferred from another source on the same host, and not copied from a
   sibling manifest. The date the page was read goes in the manifest.
2. **The `authority_level` is justified in the pull request body.** A
   locality's own parcel layer and a statewide aggregation of locality
   submissions are not the same authority over the same ground.
3. **The recorded fixture was read for surprises.** It is a real
   government response, so it can carry a name, an address, or an owner
   where none was expected. Anything of that kind decides the
   classification, and it decides it before the merge.
4. **The capability mapping says what the layer actually returns.** A
   layer mapped to `zoning.lookup` has to return zoning districts, not a
   planning area or a comprehensive-plan category that reads like one.

A reviewer who cannot verify the terms says so and the manifest stays
`declared_state: proposed`. A proposed manifest is inventory: it records
that the service exists and that its terms are unresolved, which is worth
more than an empty registry and is not the same as an active source.

## Deprecating or transferring a source

The lifecycle field is `declared_state`, and only two of its transitions
are judgment calls a person makes.

- **A source that is down is not deprecated.** Outages live in
  `operational_state`, which scheduled probes write and source selection
  reads, and no pull request is opened for a Tuesday outage
  (design/source-registry.md § 3). A source gone for weeks is a different
  finding and does become a pull request.
- **Retiring a source** means the publisher took the service away, or the
  terms changed to forbid automated access. It moves to
  `declared_state: retired` with the reason and the date in the manifest.
  The manifest stays in the repository. Deleting it loses the record that
  Virginia once published this and stopped.
- **Transferring a source** happens when a publisher moves a layer to a
  new service, which government GIS does regularly. The manifest keeps
  its `id` — the id is how fixtures, tests, and the audit trail refer to
  it — and the `service_url` and layer numbers change in one reviewed
  pull request alongside a re-recorded fixture.
- **A capability is retired** the same way, and never silently: something
  in `sources/capabilities.yaml` is what tools bind to, so removing one
  breaks a tool. The pull request that retires it either removes the tool
  or says which capability the tool moves to.

## Changing this file

By pull request, like everything else. Adding a name to the table needs
that person to say yes in the thread — a review queue someone was
volunteered for is not a review queue.
