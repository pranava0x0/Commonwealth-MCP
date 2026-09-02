# Security policy

## Reporting a vulnerability

Report privately through GitHub, at
[Security → Report a vulnerability](https://github.com/pranava0x0/Commonwealth-MCP/security/advisories/new).
That channel keeps the report between you and the maintainer until there
is a fix. Please do not open a public issue for anything exploitable.

One maintainer reads these, [@pranava0x0](https://github.com/pranava0x0),
so expect a first reply in about a week rather than the same day. If a
week passes with no reply, an issue saying only "sent a private security
report on <date>, no reply yet" is a fair nudge and gives nothing away.

Tell us what you can: what you did, what happened, and what you expected.
A recorded request and response is worth more than a description of one.

## What this project is, for scoping

Commonwealth-MCP reads public government data. It runs locally over stdio,
holds no accounts, no credentials, and no user data, and writes nothing
back to any government service. There is no deployment to attack today,
which shapes what counts as a finding.

**In scope:**

- Anything that gets an outbound request past the egress policy: a host
  outside the manifest's allowlist, a private or metadata address, a
  redirect that leaves the host set, an unbounded response.
  `design/security-and-data-handling.md` § 2 is the rule list, and each
  rule has a refusal test in `tests/core/test_egress.py`.
- Text from a government source that reaches a model as instruction
  rather than as data. Published records are untrusted content here, and
  the envelope keeps source text inside `data` for that reason.
- Anything that makes the server write, delete, or authenticate. It has
  no write path by construction, so a way to reach one is a finding.
- Path traversal or code execution through a source manifest, which is
  the one file type this project invites strangers to send.
- A source manifest that causes personal data to be cached, logged, or
  returned where the classification says it should not be.

**Not in scope:**

- A government service being down, slow, or rate-limiting. That is
  coverage, and the envelope reports it.
- A government publisher's own data being wrong, stale, or surprising.
  Those go in [design/source-quirks.md](../design/source-quirks.md) as
  ordinary issues.
- Anything that needs someone to already have your shell. A local process
  reading your own files is not a bypass.
- Denial of service by running the tool at a government service on
  purpose. Please do not; the politeness budgets exist so that no one has
  to.

## What happens next

One pull request carries the fix, the test that pins it, and the note in
the security spec. Every egress rule ships with a request that must be
refused, so a rule added in response to a report arrives with the report's
own case as its test. You get credit in the advisory unless you ask not to.
