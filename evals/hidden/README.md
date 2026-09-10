# The hidden half of the split

`design/bench.md` § 3. This directory mirrors `evals/tasks/` and
`evals/skills/`, and holds mutated variants of the public tasks —
different parcels, dates and aliases — plus the trap-pool rotation.

It is maintainer-held and normally absent from a checkout. The runner
loads it when it is present and records which splits a run covered, so
the split works from the first published number rather than being
retrofitted onto numbers already in print.

Everything under this directory except this file is ignored by git.
