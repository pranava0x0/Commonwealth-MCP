---
name: public-meeting-brief
description: >
  Prepare a brief on a Virginia local meeting: identify the session,
  check for changes in the notice, and report the published agenda items
  that concern the reader. Use for a meeting preview or agenda question.
license: Apache-2.0
compatibility: Requires the civic or all profile of Commonwealth-MCP.
metadata:
  commonwealth:
    required_capabilities: [meeting.search, meeting_agenda.lookup]
    prompt_input: question
    example_prompt: What was on the Richmond City Planning Commission agenda on September 1, 2026?
---

# Public meeting brief

**Step 1 — Identify the meeting.** Resolve the named Virginia government.
If a name matches a county and a city, show the candidates and ask.
Use the requested date or window and body with `meeting.search`. When using
a monthly calendar, match the exact date as well as the body. Two sessions
can share a day; show their times and ask if the distinction matters.

**Step 2 — Read the notice before the agenda.** State the date, local time,
body and location as published. Read any cancellation or rescheduling
comment alongside the agenda status. A final agenda can belong to a
cancelled meeting. A county calendar returned for a town does not tell you
whether the town council met. Stop if the calendar reports a gap or outage;
if it answered completely but found nothing, say which calendar and window
you checked.

**Step 3 — Read the published items.** Carry the source ID and event ID
from the same calendar record into `meeting_agenda.lookup`. Follow the
next page until the requested item is found, or until the agenda ends if
summarizing the whole meeting. Keep an item's matter file and the
publisher's action wording beside its title. A heading may have neither.
A proposal on an agenda can still be awaiting a decision.

Give the reader the meeting notice and a short list of relevant items,
each with its source link. If the detail source failed, report the notice
you did retrieve and leave the agenda unknown. If the API returned no
items, link the publisher's agenda when available; do not describe the
meeting as having had no business. Stop there unless the question asks
about a decision or individual votes.
