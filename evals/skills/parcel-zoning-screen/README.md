# Eval tasks: parcel-zoning-screen

Seven tasks in the `design/bench.md` § 2 format, covering the whole walk and
one trap per failure mode that is buildable against today's fixtures.
Two of them, added 2026-09-07 with the first town sources, are the
walk's two-source cases: a town and its county both answering for one
point, and a town's district read over the county's parcel polygon.

The runner is `commonwealth eval run`, which does not exist yet (#28 builds
it). Until it does, `tests/test_skills.py` replays six of these cases through
the tools directly, so the walk is executable
rather than described. The tasks below are what the runner will score once
it exists; the replay test is what stops them drifting from the code in the
meantime.

Each `fixtures:` entry names a directory under `tests/fixtures/sources/`.
Nothing here reaches the network.
