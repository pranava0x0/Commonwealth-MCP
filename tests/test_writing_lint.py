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

import pytest

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
    "code they produced. See the GitHub issues for what's next — priority-"
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


# --------------------------------------------------------------------------
# 2026-08-29. Every string below is verbatim from this repo or its site, and
# every one passed the checker as it stood. They were reported as unreadable
# by a reader coming to the project new, which is the audience the docs
# exist for. Grouped by the habit each one shows.
# --------------------------------------------------------------------------
MAXIMS = [
    ("Publisher-side quirks are not bugs to fix silently.", "maxim-voice"),
    ("The trail is not a log bolted on afterward.", "maxim-voice"),
    ("Telling those apart is the product.", "maxim-voice"),
    ("A registry gap and a typed error are in the walk on purpose.",
     "maxim-voice"),
    ("A quirk that affects behaviour has a test.", "aphorism-voice"),
    ("A Chosen record is not permanent, but reopening one costs more.",
     "not-but-maxim"),
]

SLOGAN_HEADINGS = [
    "### 3.1 Authority Before Convenience",
    "### 3.2 Semantic Tools, Boring Adapters",
    "### 3.5 Evidence Over Confidence Scores",
]

# Headings that state their subject plainly. These outnumber the slogans in
# the tree and none of them may trip the rule.
PLAIN_HEADINGS = [
    "### What does not work yet",
    "## 2. Virginia counties that enclose an independent city are donuts",
    "### 11.1 Example Manifest",
    "## 4. Architecture Overview",
    "#### Discovery then retrieval",
    "### 5. Civic gap, stated plainly",
]


@pytest.mark.parametrize("text,rule", MAXIMS)
def test_flags_proverb_voice(tmp_path, text, rule):
    """Each of these states a principle. None tells a reader what the code
    does or what to do next."""
    target = tmp_path / "sample.md"
    target.write_text(text + "\n")
    _, out = _run("", "--files", str(target))
    assert rule in out, f"{rule} did not fire on {text!r}:\n{out}"


@pytest.mark.parametrize("heading", SLOGAN_HEADINGS)
def test_flags_title_case_slogan_headings(tmp_path, heading):
    target = tmp_path / "sample.md"
    target.write_text(heading + "\n\nBody text.\n")
    _, out = _run("", "--files", str(target))
    assert "slogan-heading" in out, out


@pytest.mark.parametrize("heading", PLAIN_HEADINGS)
def test_plain_headings_survive(tmp_path, heading):
    """The rule keys on Title Case, so it must be case-sensitive. Compiled
    with re.I it flagged every one of these instead."""
    target = tmp_path / "sample.md"
    target.write_text(heading + "\n\nBody text.\n")
    _, out = _run("", "--files", str(target))
    assert "slogan-heading" not in out, out


def test_flags_a_sentence_with_no_verb(tmp_path):
    """From docs/index.html: a caption standing where a sentence belonged.
    It asserts nothing, so the reader has to supply the claim."""
    target = tmp_path / "sample.md"
    target.write_text(
        "A recorded walk across the registry and geo tools, one card "
        "per call.\n")
    _, out = _run("", "--files", str(target))
    assert "appositive-fragment" in out, out


@pytest.mark.parametrize("sentence", [
    "The layer carries 134 rows for Virginia's 133 counties and cities.",
    "A coordinate in a town returns the town and its county, since both "
    "govern that ground.",
    "Every answer says where it came from, when it was fetched, and what "
    "was not searched.",
    "The measurements: selection accuracy falls below 90% at 10 tools, "
    "and further after that.",
])
def test_real_sentences_are_not_called_fragments(tmp_path, sentence):
    target = tmp_path / "sample.md"
    target.write_text(sentence + "\n")
    _, out = _run("", "--files", str(target))
    assert "appositive-fragment" not in out, out


def test_flags_a_cross_reference_welded_on_with_a_dash(tmp_path):
    target = tmp_path / "sample.md"
    target.write_text(
        "Results split into source entries and evidence objects so mixed "
        "results show which source backs which record — full contract in "
        "the envelope spec.\n")
    _, out = _run("", "--files", str(target))
    assert "welded-crossref" in out, out


def test_flags_mirrored_clauses(tmp_path):
    """From the site: two halves built to balance rather than to inform."""
    target = tmp_path / "sample.md"
    target.write_text(
        "Calls that reach the county's live service show the outbound "
        "requests; calls that never leave the registry say so.\n")
    _, out = _run("", "--files", str(target))
    assert "antithesis-parallel" in out, out


def test_site_copy_is_scanned(tmp_path):
    """docs/index.html is the first thing most readers see. It sat outside
    the scan set while carrying the worst of these."""
    from pathlib import Path as _P
    assert "docs/index.html" in (_P(ROOT) / "tools" / "check_writing.py"
                                 ).read_text()
    code, out = _run("", "--files", str(ROOT / "docs" / "index.html"))
    assert "docs/index.html" in out or code == 0


# --------------------------------------------------------------------------
# The site builds about half its visible copy in JavaScript. prose_lines_html
# has to strip <script> — the embedded data blocks are script tags full of
# publisher-supplied field names, and scanning those as prose is noise — so
# every JS-built string was invisible to the checker. "the tool never
# guesses" survived a full pass that way.
# --------------------------------------------------------------------------
JS_PAGE = """<html><head><title>t</title></head><body>
<div id="x"></div>
<script type="application/json" id="data">{"n":"leverage the robust pipeline"}</script>
<script>
// a comment mentioning leverage, which is an engineering note not copy
const q = document.querySelector("#x .thing");
const url = "https://example.gov/arcgis/rest/services";
x.textContent = "%s";
</script>
</body></html>
"""


@pytest.mark.parametrize("copy,rule", [
    ("Ambiguous — 2 candidates returned; the tool never guesses:",
     "self-praise"),
    ("Telling those apart is the product.", "maxim-voice"),
    ("This leverages a robust pipeline.", "llm-register"),
])
def test_scans_copy_built_in_javascript(tmp_path, copy, rule):
    target = tmp_path / "page.html"
    target.write_text(JS_PAGE % copy)
    code, out = _run("", "--files", str(target))
    assert rule in out, f"{rule} did not fire on JS-built copy:\n{out}"
    assert code == 1


def test_js_scan_ignores_selectors_urls_comments_and_data(tmp_path):
    """Three things in a script tag are not prose: CSS selectors, URLs, and
    the embedded JSON data blocks (whose strings are the publisher's field
    names, not this repo's writing). A rule firing on any of them would
    make the scan useless noise."""
    target = tmp_path / "page.html"
    target.write_text(JS_PAGE % "A plain sentence about parcels.")
    code, out = _run("", "--files", str(target))
    assert code == 0, out
    assert "leverage" not in out, "scanned a JSON data block or a comment"


def test_a_quote_that_wraps_across_lines_is_still_exempt(tmp_path):
    """Prose wraps, so a quotation regularly opens on one line and closes on
    the next. Scanning line by line saw an unterminated quote and flagged
    the phrase inside it — the exact case the exemption exists for. This
    shape came from a commit message explaining which phrase was removed."""
    target = tmp_path / "sample.md"
    target.write_text(
        "The maxims are gone from the specs. \"Publisher-side\n"
        "quirks are not bugs to fix silently\" now says what to do.\n")
    code, out = _run("", "--files", str(target))
    assert "maxim-voice" not in out, out
    assert code == 0


def test_quotes_do_not_smuggle_prose_past_a_rule(tmp_path):
    """The exemption is for quoting someone. An unclosed quote must not turn
    the rest of a document into a blind spot."""
    target = tmp_path / "sample.md"
    target.write_text('He said "hello there friend" and then this '
                      'leverages a robust pipeline.\n')
    code, out = _run("", "--files", str(target))
    assert "llm-register" in out, out
