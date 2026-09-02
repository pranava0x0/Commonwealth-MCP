# Eval tasks: parcel-zoning-screen

Five tasks in the `design/bench.md` § 2 format, covering the whole walk and
one trap per failure mode that is buildable against today's fixtures.

The runner is `commonwealth eval run`, which does not exist yet (#28 builds
it). Until it does, `tests/test_skill_parcel_zoning_screen.py` replays the
same four cases through the tools directly, so the walk is executable
rather than described. The tasks below are what the runner will score once
it exists; the replay test is what stops them drifting from the code in the
meantime.

Each `fixtures:` entry names a directory under `tests/fixtures/sources/`.
Nothing here reaches the network.
