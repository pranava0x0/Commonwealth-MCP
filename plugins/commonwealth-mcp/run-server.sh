#!/usr/bin/env sh
# Launcher wrapper for commonwealth MCP server that resolves the executable
# even if the virtual environment has not been activated.
set -e

# If commonwealth is already in PATH, use it
if command -v commonwealth >/dev/null 2>&1; then
    exec commonwealth "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Check repo root .venv
if [ -x "$REPO_DIR/.venv/bin/commonwealth" ]; then
    exec "$REPO_DIR/.venv/bin/commonwealth" "$@"
fi

# Check current directory .venv
if [ -x "$PWD/.venv/bin/commonwealth" ]; then
    exec "$PWD/.venv/bin/commonwealth" "$@"
fi

# If uv is available, run via uv in repo
if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$REPO_DIR" commonwealth "$@"
fi

exec python3 -m commonwealth.cli "$@"
