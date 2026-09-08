#!/usr/bin/env python3
"""Review authored text, including wrapped phrases and quoted project copy.

Run: python3 tools/check_prose_local.py [--selftest] [--json PATH]
Optional: --history scans every reachable commit message; --github-dir DIR
reads previously downloaded GitHub issues/prs JSON. No network requests.
Findings need editorial review; they do not establish who wrote the text.
"""
import argparse
import ast
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize
import check_writing as base

ROOT = Path(__file__).resolve().parents[1]
RULES = [r for r in base.RULES if not r.copy_only] + [
    base.Rule('unsupported-comparison', 'WARN', r'\b(?:most|every|almost every) (?:other )?(?:systems?|projects?)\b', 'Name evidence for the comparison or remove it.'),
    base.Rule('empty-means-absence', 'WARN', r'\b(?:checked and absent|means [^.!?]{0,65}there is nothing|no record rather than|holds nothing)\b', 'Describe the query and its scope; no match does not establish absence.'),
    base.Rule('purpose-kicker', 'WARN', r'\b(?:what the whole project is for|wrong twice|the distinction that matters|nothing else makes sense|the one thing that matters)\b', 'Replace the closing slogan with useful information.'),
    base.Rule('artifact-drama', 'WARN', r'\b(?:scar tissue|broke on contact|traps? [^.!?]{0,30}(?:sprung|set for)|keeps? [^.!?]{0,30}honest)\b', 'Describe the defect or decision directly.'),
]
# Publisher records and checker examples must remain verbatim.
EXCLUDED = ('tests/fixtures/', 'tests/toolsnaps/', 'research/raw/', 'base-files/')
EXACT = {'tools/check_writing.py', 'tests/test_writing_lint.py'}
SUFFIXES = {'.md', '.txt', '.py', '.html', '.js', '.css', '.yaml', '.yml', '.toml'}


def joined(lines):
    """Join adjacent prose lines, retaining the first physical line number."""
    buf, start, last = [], None, None
    for n, text in lines:
        if not text.strip() or (last is not None and n > last + 1):
            if buf:
                yield start, ' '.join(buf)
            buf, start = [], None
        if text.strip():
            if start is None: start = n
            buf.append(text.strip())
        last = n
    if buf: yield start, ' '.join(buf)


def units(path, text):
    if path.suffix == '.py':
        # Token positions keep separate comments separate; AST limits strings
        # to docstrings and runtime/example copy, not negative test fixtures.
        yield from joined((t.start[0], t.string.lstrip('# ')) for t in
                          tokenize.generate_tokens(io.StringIO(text).readline)
                          if t.type == tokenize.COMMENT)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    yield node.body[0].lineno, ' '.join(doc.split())
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if not str(path).startswith('tests/') and len(node.value.split()) >= 5:
                    yield node.lineno, ' '.join(node.value.split())
    elif path.suffix == '.html':
        yield from joined(base.prose_lines_html(text))
        yield from base.prose_lines_js_in_html(text)
    elif path.suffix in {'.md', '.txt'}:
        # Strip fences/URLs, but retain quotations: authors can quote their own copy.
        clean = re.sub(r'```.*?```|~~~.*?~~~', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
        clean = re.sub(r'https?://[^\s)>]+', '', clean)
        yield from joined(enumerate(clean.splitlines(), 1))
    else:
        yield from joined(enumerate(text.splitlines(), 1))


def scan(source, rows):
    for hit in base.scan_text(source, rows, RULES):
        yield {'source': source, 'line': hit.locator or hit.line_no, 'rule': hit.rule.id,
               'level': hit.rule.level, 'matched': hit.matched, 'why': hit.rule.why}


def selftest():
    bad = [('README.md', 'Most systems\nshow the same blank.'),
           ('README.md', 'This is "seamless integration".'),
           ('x.py', "# It's worth\n# noting the result."),
           ('x.py', 'message = "This is seamless integration for residents."')]
    for name, text in bad:
        assert list(scan(name, units(Path(name), text))), (name, text)
    for name, text in [('x.py', 'seamless_parser = 1'), ('x.md', 'A comprehensive plan is a land-use document.'), ('x.md', 'The query matched no records within one kilometre.')]:
        assert not list(scan(name, units(Path(name), text))), text
    print('Selftest: 4 bad examples detected; 3 valid examples accepted.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--history', action='store_true')
    ap.add_argument('--github-dir', type=Path)
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    if args.selftest:
        selftest(); return 0
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    hits, errors, skipped, count, words = [], [], [], 0, 0
    for name in sorted(set(names)):
        if not name: continue
        p = ROOT / name
        if name.startswith(EXCLUDED) or name in EXACT or p.suffix not in SUFFIXES:
            skipped.append(name); continue
        try:
            rows = list(units(Path(name), p.read_text()))
            count += 1; words += sum(len(t.split()) for _, t in rows)
            hits.extend(scan(name, rows))
        except (OSError, UnicodeError, SyntaxError, tokenize.TokenError) as exc:
            errors.append(f'{name}: {exc}')
    if args.history:
        log = subprocess.check_output(['git', 'log', '--all', '--format=%H%x1f%B%x1e'], cwd=ROOT, text=True)
        for entry in log.split('\x1e'):
            if '\x1f' in entry:
                sha, body = entry.strip().split('\x1f', 1)
                hits.extend(scan('commit '+sha[:12], joined(enumerate(body.splitlines(), 1))))
    if args.github_dir:
        for name in ('issues', 'prs'):
            for row in json.loads((args.github_dir / (name+'.json')).read_text()):
                if name == 'issues' and 'pull_request' in row: continue
                body = row['title']+'\n\n'+(row.get('body') or '')
                hits.extend(scan(row['html_url'], units(Path('github.md'), body)))
    hits = list({(h['source'], h['line'], h['rule'], h['matched']): h for h in hits}.values())
    report = {'files': count, 'words': words, 'skipped': skipped, 'errors': errors, 'findings': hits}
    if args.json: args.json.write_text(json.dumps(report, indent=2))
    for h in hits: print(f"{h['level']} {h['source']}:{h['line']} {h['rule']}: {h['matched']}")
    print(f'{count} files; {words} words; {len(skipped)} exclusions; {len(hits)} review findings; {len(errors)} errors')
    for err in errors: print(err)
    return 2 if errors or not count else int(any(h['level']=='FAIL' for h in hits))

if __name__ == '__main__':
    raise SystemExit(main())
