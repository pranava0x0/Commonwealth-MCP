#!/usr/bin/env sh
# Find the server and exec it, for a client that launches this plugin
# without an activated virtual environment.
#
# `commonwealth` is a console script inside a virtual environment, and a
# plugin is launched by a desktop client whose PATH is the login shell's,
# not a terminal's. Adding the marketplace clones this repository, so the
# checkout is reachable from here even when nothing is installed globally.
#
# The order is most-specific first. Each branch is a different way of
# having this project, and the earlier one is the one the person meant:
# a checkout they installed beats a global copy that may be an older
# release, and both beat building the clone from scratch.
set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$PLUGIN_DIR/../.." && pwd)"

# A checkout with `uv pip install -e .` already run: the editable install
# a contributor is working in.
if [ -x "$REPO_DIR/.venv/bin/commonwealth" ]; then
    exec "$REPO_DIR/.venv/bin/commonwealth" "$@"
fi

# Installed as a tool (`uv tool install commonwealth-mcp`), which is how
# this runs once GitHub issue #40 publishes the package.
if command -v commonwealth >/dev/null 2>&1; then
    exec commonwealth "$@"
fi

# A clone with nothing installed in it, which is what `/plugin marketplace
# add` leaves behind. uv resolves and builds the project on first launch,
# so this branch is slow once and fast after.
if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$REPO_DIR" commonwealth "$@"
fi

# No uv. The package has to be importable already for this to work; if it
# is not, the client reports the ImportError, which names the problem
# better than anything this script could print.
exec python3 -m commonwealth.cli "$@"
