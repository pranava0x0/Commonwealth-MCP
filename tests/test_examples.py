"""The example scripts run offline (GitHub issue #30).

design/testing-and-demos.md § 3 asks for runnable demos with an offline
fixtures mode. An example nobody runs rots into a wrong tutorial, so each
is executed here as a subprocess exactly as a reader would run it —
imports, argument parsing, and all — rather than having its functions
called directly.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SCRIPTS = sorted(p for p in EXAMPLES.glob("*.py")
                 if not p.name.startswith("_"))


def test_there_are_examples_to_run():
    assert SCRIPTS, "no example scripts — the basis for these tests vanished"
    print(f"{len(SCRIPTS)} example scripts")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_each_example_runs_offline_and_prints_an_answer(script):
    proc = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, cwd=ROOT,
                          timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "recorded responses" in out, (
        "an example must say which mode it ran in")
    # Every example prints the coverage dimensions: an empty answer
    # means something different depending on which one says why.
    assert "coverage: registry=" in out, out[-800:]
    assert len(out.splitlines()) > 10, "an example that prints nothing"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_each_example_offers_a_live_mode(script):
    """The offline mode is the default and the live one has to be
    reachable, or `--fixtures` is not a mode, it is the only behaviour."""
    proc = subprocess.run([sys.executable, str(script), "--help"],
                          capture_output=True, text=True, cwd=ROOT,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "--live" in proc.stdout and "--fixtures" in proc.stdout


def test_the_readme_lists_every_script():
    """A table that drifts is worse than no table."""
    readme = (EXAMPLES / "README.md").read_text()
    missing = [p.name for p in SCRIPTS if p.name not in readme]
    assert missing == [], missing


def test_examples_do_not_import_from_the_test_suite():
    """A script someone runs should not need pytest fixtures to work. The
    offline seam lives in the package (commonwealth.fixtures) for that
    reason."""
    offenders = [p.name for p in EXAMPLES.glob("*.py")
                 if "tests." in p.read_text() or "conftest" in p.read_text()]
    assert offenders == [], offenders
