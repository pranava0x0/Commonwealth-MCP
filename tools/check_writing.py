#!/usr/bin/env python3
"""Flag AI-slop writing in this repo's docs, specs, and (later) commit text.

Adapted from Brownfield Opportunities' scripts/check_writing.py and the
register list in base-files/DESIGN.md section 11.1. This repo is docs-first
(specs, research, decision records), so the scan set is the Markdown tree
rather than product copy.

Two severities:

  BANNED (FAIL)  phrases with no legitimate use in this repo's prose: the
                 LLM register ("delve", "leverage", "robust", "seamless",
                 "comprehensive"...), puffery, chatbot openers, negation
                 slogans, and self-praise about the project's own rigor.

  REVIEW (WARN)  usually slop, sometimes load-bearing: hedge stacks,
                 em-dash pile-ups, vague attribution, "not X but Y"
                 slogans. A human decides.

What is NOT scanned:
  - research/raw/**      collected community text, quoted as-is
  - base-files/**        the user's reference material; quotes banned
                         phrases while explaining why they are banned
  - code fences, inline code, link targets
  - double-quoted spans of 12+ chars: these docs quote sources and HN
    comments verbatim, and verbatim quotes are exempt per DESIGN.md 11.1.
    Do not use quotes to smuggle your own prose past the checker.

Usage:
  python3 tools/check_writing.py                 # scan the doc tree
  python3 tools/check_writing.py --files design/foo.md
  python3 tools/check_writing.py --list          # show the rules
  python3 tools/check_writing.py --fail-on WARN  # strict
  git log -1 --format=%B | python3 tools/check_writing.py --stdin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]

DOC_GLOBS = (
    "*.md",
    "docs/**/*.md",
    "design/**/*.md",
    "research/*.md",
    "research/notes/*.md",
    # The site is the copy most people read first, and it was drifting the
    # same way the docs were. Scanned as prose with tags stripped, so class
    # names, URLs, and the embedded JSON blocks never reach a rule.
    "docs/index.html",
)
EXCLUDE_PARTS = {"raw", "base-files", "node_modules", ".git"}


class Rule:
    def __init__(self, rule_id: str, level: str, pattern: str, why: str,
                 cased: bool = False) -> None:
        self.id = rule_id
        self.level = level  # FAIL | WARN
        # Most rules match a phrase, where capitalization is noise. A few
        # match a SHAPE that only exists in one case — a Title Case slogan
        # heading is a slogan precisely because it is Title Case, and
        # matching it case-insensitively flags every ordinary sentence
        # heading instead.
        self.rx = re.compile(pattern, 0 if cased else re.I)
        self.why = why


BANNED = [
    Rule("llm-register", "FAIL",
         r"\b(delve|delving|tapestry|nestled|vibrant|leverag(?:e|es|ing)|"
         r"seamless(?:ly)?|elevate[sd]?\b|harness(?:ing)? the|empower(?:s|ing)?|"
         r"robust(?:ly|ness)?|pivotal|game[-\s]chang(?:er|ing)|"
         r"cutting[-\s]edge|ever[-\s]evolving|comprehensive(?:ly)?|"
         r"a testament to|stands? as a testament|"
         r"unlock(?:ing)? the (?:power|potential)|"
         r"navigat(?:e|ing) the complex\w*)\b",
         "LLM register word; say the specific thing instead"),
    Rule("ai-opener", "FAIL",
         r"\b(in today'?s (?:world|landscape|digital age|fast-paced)|"
         r"let'?s dive in|it'?s (?:important|worth) (?:to note|noting)|"
         r"when it comes to|at the end of the day|in conclusion|"
         r"in the (?:realm|world) of)\b",
         "chatbot connective tissue; open on the point"),
    Rule("marketing-vapor", "FAIL",
         r"\b(at your fingertips|to the next level|the ultimate solution|"
         r"designed to help you|powerful insights)\b",
         "marketing vapor; state what it does"),
    Rule("negation-slogan", "FAIL",
         r"\b(it'?s not just \w+|not just [\w\s]{1,20}(?:, but|; it'?s)|"
         r"isn'?t just about)\b",
         "negative-parallelism slogan; define by what it IS"),
    Rule("self-praise", "FAIL",
         r"\b(the honest (?:version|answer|read|gap)|here'?s the thing|"
         r"rigorous(?:ly)? (?:designed|engineered)|"
         r"we take \w+ seriously|"
         # Added 2026-08-29. The site told the reader "the tool never
         # guesses" while showing them the two candidates it returned. The
         # demonstration was already there; the boast added nothing and
         # invited doubt. Show the behaviour, drop the claim about it.
         r"(?:the )?tools? never (?:guess|guesses|lie|lies|invents?)\b|"
         r"never (?:guesses|invents|fabricates|makes (?:it|them) up)\b|"
         r"refuses? to (?:guess|invent|pretend)\b)",
         "announcing virtue instead of showing the fact"),
    Rule("hand-curated", "FAIL", r"\bhand[-\s]curated\b",
         "usually untrue of AI-drafted text; say how it was produced"),
    # Added 2026-08-28 after the README shipped "named honestly for what it
    # actually does". Claiming your own text is honest is the one quality
    # writing cannot assert about itself — the reader decides, from whether
    # the text is accurate. Say the accurate thing and stop.
    Rule("self-attributed-honesty", "FAIL",
         r"((?:named|naming|written|phrased|worded|titled) honestly\b|"
         r"\bhonestly (?:named|written|titled)\b|"
         # discourse marker only: "to be honest," / ", to be honest".
         # "forced the schema to be honest" is the word doing real work.
         r"(?:^|[,;(]\s*)to be (?:fully |completely )?honest\s*[,.)]|"
         r"\bif (?:we|I)'?(?:re| am) being honest\b|\bin all honesty\b|"
         r"\bhonest(?:ly)? about what it (?:actually |really )?"
         r"(?:does|is)\b)",
         "claiming your own honesty; state the accurate thing instead"),
    # Same session: "the exit criterion for this stage of the adopted plan
    # is met live". Bureaucratic achievement-reporting aimed at no reader.
    Rule("achievement-report", "FAIL",
         r"\b(exit criteri(?:on|a)\b[^.]{0,80}?\b(?:is|are|was|were) met|"
         r"milestone (?:is |was |has been )?achieved|"
         r"successfully (?:completed|implemented|delivered|integrated)|"
         r"as (?:per|of) the adopted plan)\b",
         "status-report register; say what works and what does not"),
    # Added 2026-08-29. The docs and the site had drifted into writing
    # proverbs about the project instead of sentences a reader can use:
    # "Publisher-side quirks are not bugs to fix silently", "The trail is
    # not a log bolted on afterward", "telling those apart is the product".
    # Each states a principle and leaves the reader no better able to use
    # the thing. Say what the code does and let the reader draw the moral.
    Rule("maxim-voice", "FAIL",
         r"(?:is|are) not (?:an? )?\w+s? to \w+ (?:silently|quietly|away)"
         r"|\bnot (?:an?|the) [\w-]+ (?:bolted|tacked|glued|slapped|welded) on"
         r"|\b(?:is|are) the (?:product|point|whole (?:design|idea|thing))\b"
         r"|\b(?:is|are) what (?:matters|the \w+ is for)\b"
         r"|\b(?:are|is) (?:all )?(?:in|on) the \w+ on purpose\b"
         r"|\bthat is the distinction that matters\b",
         "proverb voice; say what the code does, not what it stands for"),
    # Same pass: "Authority Before Convenience", "Semantic Tools, Boring
    # Adapters", "Evidence Over Confidence Scores". A heading is a label a
    # reader scans to find something. A slogan makes them read the section
    # to learn what the section is about.
    Rule("slogan-heading", "FAIL",
         r"^#{2,6}\s+(?:[\d.]+\s+)?"
         r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*\s+"
         r"(?:Before|Over|Without|Beyond|Versus|Vs\.?|Not|Then)\s+"
         r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*\s*$"
         r"|^#{2,6}\s+(?:[\d.]+\s+)?"
         r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*)+,\s+"
         r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*)+\s*$",
         "slogan heading; name what the section covers", cased=True),
]

REVIEW = [
    Rule("hedge-stack", "WARN",
         r"\b(might potentially|could possibly|may perhaps|"
         r"generally speaking|somewhat unclear|arguably)\b",
         "hedging reflex; state it or cut it"),
    Rule("em-dash-pileup", "WARN", r"—[^—\n]{0,120}—[^—\n]{0,120}—",
         "three em dashes in close succession; use sentences"),
    Rule("vague-attribution", "WARN",
         r"\b(experts (?:say|agree|argue)|studies show|"
         r"it is (?:widely )?believed|industry reports)\b",
         "name the source or drop the claim"),
    Rule("rule-of-three-intensifier", "WARN",
         r"\b(fast, simple, and \w+|simple yet powerful|fast but reliable)\b",
         "contrasting-pair / tricolon cadence; pick the real claim"),
    # Added 2026-08-28 after a count found 63 uses of honest/honesty/
    # honestly across the tree. It is this project's tic: the value is
    # real, so the word gets reached for where a precise one belongs.
    # "coverage honesty" is a named test category and stays; "an honest
    # shape", "honestly null", "verified honest" are all standing in for
    # accurate, genuinely, or faithful.
    Rule("vague-virtue-word", "WARN",
         r"\b(?:an?|the|more|most|genuinely|verified|remains?|stays?)\s+"
         r"honest\b|\bhonestly\s+(?:null|true|false|empty|shaped|"
         r"scoped|reported)\b",
         "'honest' standing in for a precise word; say accurate, "
         "complete, exact, or faithful"),
    Rule("stage-direction", "WARN",
         r"\b(consider this:|picture this:|think of it (?:as|like) a\b)\b",
         "stage direction to the reader; cut the device"),
    # Added 2026-08-29 with maxim-voice, for the softer form of the same
    # habit: "A quirk that affects behaviour has a test." True, and written
    # as folk wisdom. An instruction ("List the test name; if there is no
    # test, say so") tells a contributor what to do.
    Rule("aphorism-voice", "WARN",
         r"\bAn? [a-z][\w-]* (?:that|which) [^.;]{5,70}?\s"
         r"(?:has|needs|gets|carries|becomes|means|costs|wins|counts)\s",
         "aphorism voice; write it as an instruction — who does what"),
    # "A Chosen record is not permanent, but reopening one costs more than
    # proposing a new one." The reader has to hold a negation, a
    # concession, and a comparison to extract one rule.
    Rule("not-but-maxim", "WARN",
         r"\bis not \w+[^,.;]{0,40}, but \w+ing\b"
         r"|\bis not (?:a |an |the )?[\w-]+, but\b",
         "'not X, but Y' balance; state the rule, then the exception"),
    # "Calls that reach the live service show the real requests…; calls
    # that never leave the registry say so…". Mirrored clauses read as
    # composed rather than informative. Two plain sentences carry it.
    Rule("antithesis-parallel", "WARN",
         r"\b(\w+) that [^;.]{10,140}; \1 that\b",
         "mirrored 'X that…; X that…' clauses; use two plain sentences"),
    # "…prove which source supports which record — full contract in
    # design/provenance-envelope.md". A pointer welded to the end of a
    # sentence that was already full. Make it its own sentence.
    Rule("welded-crossref", "WARN",
         r"—\s*(?:full |the )?"
         r"(?:contract|details?|spec|rest|rationale|record|list|evidence)\b"
         r"[^.]{0,30}\b(?:in|at|lives in|see)\b"
         r"|—\s*(?:implementation|the code|callers?|clients?)\s+"
         r"(?:may|might|can|will|already)\b",
         "cross-reference welded on with an em dash; give it its own "
         "sentence"),
]

RULES = BANNED + REVIEW

# Structural slop has no phrase to match. The README's 250-word status
# paragraph passed every regex above while being the worst prose in the
# repo, which is what prompted these. Thresholds are calibrated against
# this corpus (2026-08-28: 547 prose paragraphs, median 20 words, p95 79;
# 1,900 sentences, median 11 words, p95 43), set well clear of normal so a
# hit means something.
WALL_PARAGRAPH_WORDS = 120
MEGA_SENTENCE_WORDS = 70

STRUCTURE = [
    Rule("wall-paragraph", "WARN", r"$never$",
         f"over {WALL_PARAGRAPH_WORDS} words in one paragraph; break it up "
         "or cut it"),
    Rule("mega-sentence", "WARN", r"$never$",
         f"over {MEGA_SENTENCE_WORDS} words in one sentence; it has more "
         "than one idea in it"),
    # Added 2026-08-29. "A recorded walk across the registry and geo tools,
    # one card per call." reads like a caption, not a sentence: no verb, so
    # nothing is asserted and the reader has to supply the claim. The site
    # opened three sections this way.
    Rule("appositive-fragment", "WARN", r"$never$",
         "sentence with no verb; say what the thing does"),
]
STRUCTURE_BY_ID = {r.id: r for r in STRUCTURE}

# The escape hatch. Every entry needs a reason; an unexplained entry is how
# a ban quietly stops meaning anything.
ALLOW_PHRASES: list[tuple[str, str]] = [
    ("end-to-end test", "term of art in testing; the buzzword use is still banned"),
    ("harness the", "only when preceded by 'test'/'eval' via context, see scan"),
]


class Hit:
    def __init__(self, rule: Rule, source: str, line_no: int,
                 matched: str, context: str) -> None:
        self.rule = rule
        self.source = source
        self.line_no = line_no
        self.matched = matched
        self.context = context

    def line(self) -> str:
        loc = f"{self.source}:{self.line_no}" if self.line_no else self.source
        return (f"[{self.rule.level}] {self.rule.id:26} {loc:52} "
                f"{self.matched!r} — {self.rule.why}\n"
                f"         … {self.context.strip()[:150]}")

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule.id, "level": self.rule.level,
                "source": self.source, "line": self.line_no,
                "matched": self.matched, "why": self.rule.why}


def _blank_out(text: str, pattern: str) -> str:
    """Remove matches but keep newlines so line numbers stay correct."""
    return re.sub(pattern, lambda m: "\n" * m.group(0).count("\n"), text,
                  flags=re.S)


def _drop_quotes(text: str) -> str:
    """Blank out double-quoted spans of 12+ chars, keeping line numbers.

    Verbatim quotes are exempt (DESIGN.md 11.1). These docs quote sources
    and community comments as written, and a commit message explaining why
    a phrase was removed has to name the phrase. Curly and straight quotes
    both count. Do not use quotes to smuggle your own prose past a rule.

    Run over the whole text rather than line by line: prose wraps, so a
    quotation routinely opens on one line and closes on the next. Scanning
    per line saw an unterminated quote and flagged the phrase inside it —
    which is the one case the exemption exists for.
    """
    return re.sub(r"[\"\u201c][^\"\u201d]{12,}?[\"\u201d]",
                  lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


def prose_lines_md(text: str) -> Iterator[tuple[int, str]]:
    text = _blank_out(text, r"```.*?```")
    text = _drop_quotes(text)
    for i, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"`[^`]*`", " ", raw)            # inline code
        line = re.sub(r"\]\([^)]*\)", "] ", line)      # link targets
        line = re.sub(r"<[^>]*>", " ", line)           # html tags
        yield i, line


def prose_lines_html(text: str) -> Iterator[tuple[int, str]]:
    """Visible copy from the site. Comments, <script>, and <style> go first
    (the embedded data blocks are script tags full of source-published
    strings, and a publisher's own field names are not this repo's prose),
    then tags — which takes every attribute value and URL with them."""
    text = _blank_out(text, r"<!--.*?-->")
    text = _blank_out(text, r"<script\b.*?</script>")
    text = _blank_out(text, r"<style\b.*?</style>")
    for i, raw in enumerate(text.splitlines(), 1):
        yield i, re.sub(r"<[^>]*>", " ", raw)


def prose_lines_js_in_html(text: str) -> Iterator[tuple[int, str]]:
    """String literals from the page's own script.

    Half this site's visible copy is built in JS and inserted at load time,
    so stripping <script> — which prose_lines_html has to do, or the
    embedded JSON data blocks would be scanned as prose — hid it from every
    rule. That is where "the tool never guesses" survived a full pass.

    Only quoted literals are yielded, and only ones that look like a
    sentence fragment rather than a selector, a class name, or a URL.
    """
    for m in re.finditer(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>",
                         text, re.S):
        base = text[:m.start()].count("\n") + 1
        body = m.group(1)
        body = _blank_out(body, r"/\*.*?\*/")
        for i, raw in enumerate(body.splitlines()):
            if raw.lstrip().startswith("//"):
                continue          # engineering note, not copy
            parts = []
            for lit in re.finditer(r"""(["'`])((?:[^"'`\\\n]|\\.){10,}?)\1""",
                                   raw):
                s = lit.group(2)
                if " " not in s or s.lstrip()[:1] in "#.<":
                    continue
                if s.startswith("http") or "${" in s and " " not in s:
                    continue
                parts.append(s)
            if parts:
                yield base + i, " ".join(parts)


def prose_paragraphs_html(text: str) -> Iterator[tuple[int, str]]:
    """One block per <p>/<li>/<h*>, so a sentence wrapped across source
    lines is measured whole rather than as three short lines."""
    text = _blank_out(text, r"<!--.*?-->")
    text = _blank_out(text, r"<script\b.*?</script>")
    text = _blank_out(text, r"<style\b.*?</style>")
    for m in re.finditer(r"<(p|li|h[1-6])\b[^>]*>(.*?)</\1>", text, re.S):
        body = re.sub(r"<[^>]*>", " ", m.group(2))
        body = re.sub(r"&[a-z]+;|&#\d+;", " ", body)
        body = " ".join(body.split())
        if body:
            yield text[:m.start()].count("\n") + 1, body


def allowed_spans(line: str) -> list[tuple[int, int]]:
    spans = []
    low = line.lower()
    for phrase, _reason in ALLOW_PHRASES:
        start = 0
        p = phrase.lower()
        while (idx := low.find(p, start)) != -1:
            spans.append((idx, idx + len(p)))
            start = idx + 1
    return spans


def scan_text(source: str, units: Iterable[tuple[int, str]],
              rules: list[Rule]) -> Iterator[Hit]:
    for loc, line in units:
        if not line.strip():
            continue
        skip = allowed_spans(line)
        for rule in rules:
            for m in rule.rx.finditer(line):
                # Overlap, not containment: the rule may match a wider span
                # than the allowed phrase.
                if any(m.start() < e and s < m.end() for s, e in skip):
                    continue
                yield Hit(rule, source, loc, m.group(0), line)


def prose_paragraphs_md(text: str) -> Iterator[tuple[int, str]]:
    """Prose paragraphs with their starting line numbers. Fenced code,
    tables, lists, headings, and block quotes are skipped: their length
    carries information rather than padding, and wrapping a table is not
    the writer's choice."""
    text = _blank_out(text, r"```.*?```")
    line_no, buf, start = 0, [], 1
    for i, raw in enumerate(text.splitlines(), 1):
        if raw.strip():
            if not buf:
                start = i
            buf.append(raw)
            continue
        if buf:
            yield start, "\n".join(buf)
            buf = []
    if buf:
        yield start, "\n".join(buf)


def _is_prose(block: str) -> bool:
    """A list marker is a bullet FOLLOWED BY SPACE. `**Bold lead-in:**` is
    prose and was the single worst paragraph in this repo, so treating a
    leading asterisk as a bullet would exempt exactly the case these rules
    exist for."""
    head = block.lstrip()
    if head[:1] in {"#", "|", ">", "<"}:
        return False
    if re.match(r"^[-*+]\s", head):          # bullet + space, not **bold**
        return False
    return not re.match(r"^\d+[.)]\s", head)


# A fragment has no finite verb, so it asserts nothing — the reader has to
# guess the claim. Detecting that needs a verb list rather than a regex.
# Kept to auxiliaries plus the verbs this corpus actually uses, and paired
# with two guards (opens on a determiner, contains a comma) so an ordinary
# sentence built from a verb not on the list cannot trip it.
_FINITE_VERBS = frozenset("""
is are was were be been being am has have had do does did can could may might
must shall should will would returns return carries carry says say makes make
gets get gives give takes take shows show holds hold names name reports report
means mean needs need lives live sits sit runs run ships ship fails fail
passes pass comes come goes go knows know sees see keeps keep puts put uses use
works work covers cover queries query resolves resolve emits emit raises raise
adds add stops stop starts start finds find picks pick answers answer counts
count appears appear exists exist becomes become stays stay costs cost affects
affect declares declare publishes publish records record surfaces surface
falls fall rises rise remains remain contains contain includes include
requires require applies apply chooses choose synthesizes synthesize
retrieves retrieve invests invest shrank succeeds succeed survived pitch
pitches reads read wants want assigns assign backs back
""".split())

_FRAGMENT_LEAD = re.compile(
    r"^(?:A|An|The|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Every"
    r"|Each|No)\b", re.I)

# Below this a verbless clause is a caption or a label, not a failed
# sentence; above it the writer meant to make a claim and did not.
FRAGMENT_MIN_WORDS = 7


def _is_appositive_fragment(sentence: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", sentence)
    if len(words) < FRAGMENT_MIN_WORDS or "," not in sentence:
        return False
    # A colon introduces a list or an example, and the clause before it is
    # a label by design ("The measurements: selection accuracy falls…").
    # That is a different construction from a sentence that meant to have
    # a verb and lost it.
    if ":" in sentence:
        return False
    if not _FRAGMENT_LEAD.match(sentence.strip()):
        return False
    return not any(w.lower() in _FINITE_VERBS for w in words)


def scan_structure(source: str,
                   paragraphs: Iterable[tuple[int, str]]) -> Iterator[Hit]:
    for line_no, block in paragraphs:
        if not _is_prose(block):
            continue
        clean = re.sub(r"`[^`]*`", " ", block)
        clean = re.sub(r"\]\([^)]*\)", "] ", clean)
        words = len(clean.split())
        if words > WALL_PARAGRAPH_WORDS:
            yield Hit(STRUCTURE_BY_ID["wall-paragraph"], source, line_no,
                      f"{words} words", clean)
        for sentence in re.split(r"(?<=[.!?])\s+", clean):
            n = len(sentence.split())
            if n > MEGA_SENTENCE_WORDS:
                yield Hit(STRUCTURE_BY_ID["mega-sentence"], source, line_no,
                          f"{n} words", sentence)
            if _is_appositive_fragment(sentence):
                yield Hit(STRUCTURE_BY_ID["appositive-fragment"], source,
                          line_no, sentence.strip()[:60], sentence)


def prose_lines_py(text: str) -> Iterator[tuple[int, str]]:
    """Comments and docstrings from a Python file. Code comments are prose
    the same way docs are — they are read by people, and they rot the same
    way — so they get the same lint. Code itself is not scanned: a variable
    named `robust_parser` is a naming question, not a register question."""
    import ast
    import io
    import tokenize
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.start[0], tok.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=True)
        if not doc:
            continue
        base = getattr(node, "lineno", 1)
        for offset, line in enumerate(doc.splitlines()):
            yield base + offset, line


def collect_files() -> list[Path]:
    out: list[Path] = []
    for pattern in DOC_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file() and not (set(p.parts) & EXCLUDE_PARTS):
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="*", default=None,
                    help="Scan these files instead of the doc tree.")
    ap.add_argument("--stdin", action="store_true", help="Scan text on stdin.")
    ap.add_argument("--only", nargs="*", default=None,
                    help="Run only these rule ids.")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--list", action="store_true", help="List rules and exit.")
    ap.add_argument("--code", action="store_true",
                    help="Also scan comments and docstrings under src/, "
                         "tests/, and tools/.")
    ap.add_argument("--fail-on", default="FAIL",
                    choices=["FAIL", "WARN", "NEVER"])
    args = ap.parse_args()

    if args.list:
        for r in RULES + STRUCTURE:
            print(f"{r.level:5} {r.id:26} {r.why}")
        return 0

    rules = [r for r in RULES if not args.only or r.id in args.only]
    hits: list[Hit] = []

    if args.stdin:
        text = sys.stdin.read()
        hits += list(scan_text(
            "<stdin>",
            enumerate(_drop_quotes(text).splitlines(), 1), rules))
    else:
        targets = ([Path(f).resolve() for f in args.files]
                   if args.files else collect_files())
        if args.code and not args.files:
            for sub in ("src", "tests", "tools"):
                targets += sorted((ROOT / sub).rglob("*.py"))
            # A rule table has to quote the phrases it bans, and every rule
            # here carries a comment naming the prose that prompted it. The
            # checker scanning itself reports its own vocabulary as slop —
            # the same reason base-files/ is excluded.
            targets = [t for t in targets if t.name != Path(__file__).name]
        for path in targets:
            rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) \
                else str(path)
            text = path.read_text()
            if path.suffix == ".py":
                hits += list(scan_text(rel, prose_lines_py(text), rules))
                continue
            if path.suffix == ".html":
                hits += list(scan_text(rel, prose_lines_html(text), rules))
                hits += list(scan_text(rel, prose_lines_js_in_html(text),
                                       rules))
                if not args.only:
                    hits += list(scan_structure(
                        rel, prose_paragraphs_html(text)))
                continue
            hits += list(scan_text(rel, prose_lines_md(text), rules))
            # Structural rules judge authored prose. research/notes/ is raw
            # captured research kept for provenance, dense by intent and
            # superseded by ../research/README.md; length is not a defect there.
            if not args.only and "notes" not in path.parts:
                hits += list(scan_structure(rel, prose_paragraphs_md(text)))

    fails = [h for h in hits if h.rule.level == "FAIL"]
    warns = [h for h in hits if h.rule.level == "WARN"]
    for h in fails + warns:
        print(h.line())

    scanned = "stdin" if args.stdin else f"{len(targets)} files"
    print("\n" + "=" * 78)
    print(f"{len(fails)} banned · {len(warns)} review   (scanned {scanned})")
    if not hits:
        print("no slop found")
    if args.json:
        args.json.write_text(json.dumps([h.to_dict() for h in hits], indent=1))

    if args.fail_on == "NEVER":
        return 0
    if fails:
        return 1
    if args.fail_on == "WARN" and warns:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
