"""Trace two items at the same meeting to their separate vote records."""
from _common import heading, run, show_envelope

from commonwealth.domains.civic import get_item_votes, get_meeting_agenda, search_meetings


async def pages(ctx, reader, arguments):
    """Follow the publisher's continuation while each page answers."""
    for _ in range(20):
        env = await reader(ctx, **arguments)
        show_envelope(env)
        if not env.data.get("results") or env.coverage.execution.value != "complete":
            print("  This source could not answer; the remaining records are unknown.")
            return
        block, = env.data["results"]
        yield block, {e.id: e.locator for e in env.evidence}
        arguments = block["next"]
        if arguments is None:
            return
    print("  Stopped after 20 pages. More records may follow.")


async def walk(ctx):
    heading("Find the September 1, 2026 Richmond City Planning Commission meeting")
    notice = await search_meetings(ctx, "Richmond City", "2026-09-01", "2026-09-01",
                                   body="Planning Commission")
    show_envelope(notice)
    meetings = [(block["source_id"], r) for block in notice.data.get("results", [])
                for r in block["records"] if r["body"] == "Planning Commission"]
    if len(meetings) != 1 or notice.coverage.pagination.value != "complete":
        print("The calendar did not establish one meeting. Stop before matching a motion.")
        return
    source, meeting = meetings[0]
    print(f"  {meeting['body']}, {meeting['date']} at {meeting['time']} {meeting['time_zone']}")

    wanted = {"PDRMIN 2026.016", "ORD. 2026-093"}
    heading("Read each action and check the votes on that item")
    async for agenda, citations in pages(ctx, get_meeting_agenda, {
            "source_id": source, "event_id": meeting["event_id"]}):
        for item in agenda["records"]:
            if item["matter_file"] not in wanted:
                continue
            action = (item["action"] or "no action published").strip()
            print(f"  {item['matter_file']}: {action} ({citations[item['evidence_refs'][0]]})")
            async for votes, refs in pages(ctx, get_item_votes, {
                    "source_id": source, "item_id": item["item_id"]}):
                if not votes["records"] and votes["offset"] == 0:
                    print("  The endpoint returned no individual votes for this item.")
                for vote in votes["records"]:
                    print(f"  {vote['person']}: {vote['vote']} ({refs[vote['evidence_refs'][0]]})")


if __name__ == "__main__":
    raise SystemExit(run(__doc__, walk))
