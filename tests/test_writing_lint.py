"""The writing checker's own regression set.

Every rule here exists because prose that shipped in this repo got past an
earlier version of the checker. The paragraph in `SHIPPED_SLOP` is the real
one from README.md, removed 2026-08-28; it passed every rule the checker
had at the time while being the worst writing in the tree.

A checker with no test is a checker that quietly stops catching things.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_writing.py"

# Verbatim from README.md before 2026-08-28. Trimmed to the tells.
SHIPPED_SLOP = (
    "**Current state: contract spike shipped (2026-08-27).** The exit "
    "criterion for this stage of the adopted plan is met live: a real "
    "parcel query returns a full evidence envelope through an MCP server. "
    "Civic's first tool is a direct-citation lookup, not the full-text "
    "search the design sketch names — named honestly for what it actually "
    "does. 13 seed jurisdictions with the trap pairs, 135 offline tests "
    "over recorded fixtures, every guard mutation-checked. 14 of 15 "
    "decisions are Chosen; design docs and research live alongside the "
    "code they produced. See backlog.md for what's next — priority-"
    "ordered, not date-ordered, because the ordering reflects what the "
    "project needs next rather than when each item happened to be written "
    "down, which is the distinction that matters to a reader deciding "
    "where to spend attention."
)

LEGITIMATE = (
    "The manifest schema freezes when the first three localities have "
    "forced the schema to be honest. Coverage says which kind of empty a "
    "result is."
)


def _run(text: str, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=text, capture_output=True, text=True, cwd=ROOT)
    return proc.returncode, proc.stdout


def test_catches_the_slop_that_shipped(tmp_path):
    target = tmp_path / "sample.md"
    target.write_text(SHIPPED_SLOP + "\n")
    code, out = _run("", "--files", str(target))
    for rule in ("self-attributed-honesty", "achievement-report",
                 "wall-paragraph"):
        assert rule in out, f"{rule} no longer fires on the paragraph it " \
                            f"was written for:\n{out}"
    assert code == 1, "banned phrases must fail the build, not warn"


def test_does_not_flag_honest_used_as_a_real_word(tmp_path):
    """'forced the schema to be honest' is the word doing work, not an
    author vouching for themselves. This exact false positive shipped in
    design/source-registry.md."""
    target = tmp_path / "sample.md"
    target.write_text(LEGITIMATE + "\n")
    code, out = _run("", "--files", str(target))
    assert "self-attributed-honesty" not in out, out
    assert code == 0


def test_bold_lead_in_is_prose_not_a_list_item(tmp_path):
    """A paragraph opening '**Bold:**' starts with an asterisk but is not a
    bullet. Treating it as one exempted the single worst paragraph here."""
    target = tmp_path / "sample.md"
    target.write_text("**Lead-in:** " + " ".join(["word"] * 130) + "\n")
    _, out = _run("", "--files", str(target))
    assert "wall-paragraph" in out, out


def test_real_bullet_lists_are_not_flagged_for_length(tmp_path):
    target = tmp_path / "sample.md"
    target.write_text("- " + " ".join(["word"] * 130) + "\n")
    _, out = _run("", "--files", str(target))
    assert "wall-paragraph" not in out, out


def test_checker_excludes_itself_from_the_code_scan():
    """Its rule table has to quote the phrases it bans."""
    code, out = _run("", "--code")
    assert "check_writing.py" not in out, (
        "the checker is reporting its own rule definitions as slop:\n" + out)


def test_the_repo_has_no_banned_phrases():
    code, out = _run("", "--code")
    assert code == 0, out


def test_flags_honest_standing_in_for_a_precise_word(tmp_path):
    """A 2026-08-28 count found 63 uses of honest/honesty/honestly. Where
    the meaning is 'accurate' or 'faithful', say that."""
    target = tmp_path / "sample.md"
    target.write_text("The empty result is a different, honest shape, and "
                      "the vintage is honestly null at query time.\n")
    _, out = _run("", "--files", str(target))
    assert "vague-virtue-word" in out, out


def test_does_not_flag_coverage_honesty_the_named_concept(tmp_path):
    """'coverage honesty' names a test category in design/bench.md."""
    target = tmp_path / "sample.md"
    target.write_text("Coverage honesty tests assert the dimension values.\n")
    _, out = _run("", "--files", str(target))
    assert "vague-virtue-word" not in out, out
