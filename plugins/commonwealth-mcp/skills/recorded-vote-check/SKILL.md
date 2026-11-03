---
name: recorded-vote-check
description: >
  Check how a named member or body voted on a particular item of Virginia
  local business. Trace the motion to its meeting and distinguish the
  recorded action from the individual votes the publisher lists.
license: Apache-2.0
compatibility: Requires the civic or all profile of Commonwealth-MCP.
metadata:
  commonwealth:
    required_capabilities: [meeting.search, meeting_agenda.lookup, meeting_votes.lookup]
    prompt_input: question
    example_prompt: How did the Richmond City Planning Commission vote on the minutes on September 1, 2026?
---

# Recorded vote check

**Step 1 — Match the motion.** Resolve the locality. Ask for a choice if
the name is ambiguous. Use `meeting.search` for the named body and date,
then `meeting_agenda.lookup` for the source ID and event ID together.
Follow page links to find the matter file and action in the question.
A commission recommendation and a council decision can concern the same
ordinance. When more than one motion fits, show the alternatives and ask
which vote is meant.

**Step 2 — Read the votes on that item.** Pass the item's source ID and
item ID together to `meeting_votes.lookup`. If the caller already supplied
that pair from an agenda, start here. Preserve the publisher's vote labels.
Read every page before reporting a tally or saying a name is absent.
A mover, seconder or attendee has no vote to report unless a vote record
says so.

**Step 3 — Cite the action and the votes separately.** Name the body, date
and matter when established. Give the action its agenda-item citation;
give each reported vote its vote-record citation. If only the action was
published, report it and say that the endpoint returned no individual
votes. Do not infer unanimity, abstention or absence from missing rows.
If a source failed, leave the votes unknown and provide the minutes link
from the notice if available. Stop once the requested vote is accounted for.
