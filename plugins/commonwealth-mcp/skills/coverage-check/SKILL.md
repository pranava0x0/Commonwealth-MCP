---
name: coverage-check
description: >
  Work out whether this server can answer a question for a place before
  asking it, and when it cannot, say which of the three reasons applies:
  no source is registered there, a registered source is down, or the
  source is registered and its records are simply thin. Use when a lookup
  came back empty and someone needs to know what that empty means, when
  someone asks what is covered in their county, or before promising an
  answer a locality has no source behind.
license: Apache-2.0
compatibility: >
  Requires Commonwealth-MCP v0.x. The registry tools are in every profile
  from `discovery-min` up, so no profile change is needed.
metadata:
  commonwealth:
    required_capabilities:
      - boundary.lookup
    optional_capabilities:
      - parcel.lookup
      - zoning.lookup
    example_prompt: >
      Can you tell me how a parcel in Craig County is zoned? If not, say
      why not.
---

# Coverage check

An empty answer is three different facts wearing one face. The records
were searched and nothing matched. Or nothing was searched, because no
source is registered for that place. Or something was searched and the
service failed. Reporting any of them as "nothing found" produces a
confident absence that nobody can act on, and the third one produces it
intermittently, which is worse.

This walk establishes which. It is the rule the whole project rests on,
written as a workflow, and it runs entirely against the registry — no
government service is queried, so it is cheap and it works while every
upstream is down.

## 1. Establish the frame

Three things have to be separated before the question can be answered.

- **The place.** A capability is registered against a jurisdiction, and a
  jurisdiction is not a name. "Fairfax" is two governments. A town has a
  county above it, and a source registered for the county answers for the
  town through that stack. Resolve first; a coverage answer about the
  wrong government is worse than no answer.
- **The subject.** Coverage is per capability, not per place. A county can
  have a parcel source and no zoning source, and often does. Name the
  capability the question actually needs before checking anything.
- **Declared state and operational state.** A manifest says what it
  intends to be; a probe says what it was doing when last checked. A
  source can be registered, active, and unreachable. Those are different
  columns and the answer has to keep them apart.

## 2. Minimum data walk

**Step 1 — resolve the place.** Take the name, address, or coordinate to a
jurisdiction. If it is ambiguous, stop and ask, exactly as
[[whose-government]] does. Do not check coverage for a guess.

**Step 2 — ask what is registered.** Search the registry for the
capability the question needs, scoped to the resolved jurisdiction and the
governments above it. Three outcomes:

- *Sources come back.* Coverage exists on paper. Go to step 3.
- *Nothing comes back.* This is a registry gap. Say so in those terms, and
  say which place it means. Stop here; step 3 has nothing to check.
- *The capability is not in the vocabulary.* The question is outside what
  this server models at all. That is a fourth answer, and it is not a
  coverage gap: naming a subject nobody has registered a capability for
  means the project has no opinion about that place, not that the place
  lacks the thing.

**Step 3 — read the manifest of each source that came back.** What it
publishes, whose terms apply, and its stated limitations. The limitations
are the part that decides whether an answer would be worth anything: a
layer that is a curated convenience list rather than an inventory cannot
support "there is no school there", however green its status.

**Step 4 — check operational state.** Declared active is not the same as
answering. Read the status of each source, and note the reading's date.
A status older than the question's tolerance is unknown, not healthy.

## 3. Escalation table

| Finding | Next | Why |
|---|---|---|
| No source registered for the place | Report a registry gap and name the place | The caller is about to read absence as evidence; this is the sentence that stops them |
| A source above the place covers it | Say which government's source is answering | A town answered by its county's layer is a different fact from the town publishing one |
| Registered but its status is failed | Report an outage, with the reading's date | An outage is temporary and a gap is not; a caller can wait out one and not the other |
| Registered, healthy, limitations narrow | Quote the limitation | "Covered" with a layer that disclaims completeness is a promise the source did not make |
| Status reading is stale | Say the state is unknown | An old green reading says the source worked once |
| The capability is not in the vocabulary | Say the subject is unmodelled | Nobody has registered how to answer this anywhere, which is not a fact about the place |

## 4. Output contract

1. **Answerable, or not, and for which place and subject.** Named in full,
   both of them. "Zoning in Craig County" and not "that".
2. **Which of the three empties applies**, if it is not answerable: no
   source registered, source unavailable, or registered and thin.
3. **Whose source would answer.** The publisher and the government it
   belongs to, including when that government is above the one asked
   about.
4. **What the source does not cover**, in the source's own words, where a
   limitation would change how the answer is read.
5. **The date of the status reading**, whenever operational state is part
   of the answer.

## 5. Stop conditions

Done when the question is answerable and the sources behind it are named,
or when it is not and the reason is one of the three.

Refuse, and say why:

- **Whether the underlying fact is true.** This walk reports what can be
  queried, never what a query would return. A registered zoning source
  does not mean the parcel is zoned as anyone expects.
- **Whether a locality publishes data this project has not registered.**
  An unregistered locality is a gap in this registry. Most Virginia
  localities publish something; nobody has written the manifest. Say that,
  rather than implying the government publishes nothing.
- **Predicting when an outage will end**, or whether a gap will be filled.
  Point at the open issues instead.
