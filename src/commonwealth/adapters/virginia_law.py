"""Virginia Law (law.lis.virginia.gov) adapter: Code of Virginia section
text by citation, and the Code's own table of contents.

Two paths to one publisher. Section text comes from the public website,
which is plain, anonymous, server-rendered HTML with a stable structure.
A missing section is not a 404 there — the site 302-redirects to the
enclosing title's chapter listing, a page with a different, detectable
shape (design/provenance-envelope.md § 2: never guess, detect the real
signal).

The structure — titles, chapters, sections — comes from the publisher's
own JSON API at `/api/`, which is anonymous and needs no key. This
module and the manifest both said until 2026-09-08 that the JSON API was
gated behind an LIS registration, and that was wrong: the gated program
is the *legislative* API at lis.virginia.gov (bills and members, GitHub
issue #11), which is a different service run by the same division. The
law site's own API answers unauthenticated. source-quirks.md § 18
records what it has and, more to the point, what it does not: there is no
full-text search operation anywhere in it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidQuery, SourceUnavailable
from ..core.registry import SourceManifest, register_adapter_params
from .base import HtmlFetcher, HttpFetcher, egress_policy_for, log_source_call


class VirginiaLawParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str  # e.g. https://law.lis.virginia.gov/vacode
    # The publisher's JSON API, same host and same terms. Declared in the
    # manifest rather than derived from `service_url`, because a source
    # that gains a second endpoint should say so in the file a reviewer
    # reads. A manifest without it browses nothing and still looks up
    # sections.
    api_url: str | None = None


register_adapter_params("virginia_law", VirginiaLawParams)


@dataclass
class CodeEntry:
    """One row of the Code's table of contents.

    `number` and `name` are the publisher's own; `kind` says which level
    of the hierarchy it is, because a caller walking down needs to know
    what it may ask for next.
    """

    kind: str          # title | chapter | section
    number: str
    name: str


@dataclass
class CodeSection:
    citation: str
    heading: str
    paragraphs: list[str]
    source_url: str


class _SectionPageParser(HTMLParser):
    """Extracts a section's heading and body paragraphs from law.lis.
    virginia.gov's stable `#vacode` markup. `found` is the real signal —
    a page with no `data-field="body"` section is a title/chapter listing
    (the site's "not found" shape), not a section page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self.heading_parts: list[str] = []
        self.paragraphs: list[str] = []
        self._in_content = False  # inside <span id="va_code">
        self._in_h2 = False
        self._have_heading = False
        self._in_body = False
        self._body_depth = 0
        self._current_p: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]
                        ) -> None:
        attrs_d = dict(attrs)
        if tag == "span" and attrs_d.get("id") == "va_code":
            self._in_content = True
        elif (tag == "h2" and self._in_content and not self._in_body
              and not self._have_heading):
            self._in_h2 = True
        elif tag == "section" and attrs_d.get("data-field") == "body":
            self.found = True
            self._in_body = True
            self._body_depth = 1
        elif self._in_body:
            if tag == "section":
                self._body_depth += 1
            elif tag == "p":
                self._current_p = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            if self._in_h2:
                self._have_heading = True
            self._in_h2 = False
        elif self._in_body:
            if tag == "p" and self._current_p is not None:
                text = "".join(self._current_p).strip()
                if text:
                    self.paragraphs.append(text)
                self._current_p = None
            elif tag == "section":
                self._body_depth -= 1
                if self._body_depth == 0:
                    self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self.heading_parts.append(data)
        elif self._current_p is not None:
            self._current_p.append(data)


# The Code's own numbering: a digit first, then digits, dots, colons,
# letters and hyphens (title "15.2", chapter "22", section "18.2-57").
_NUMBER = re.compile(r"^[0-9][0-9.:A-Za-z-]*$")


def _segment(value: str, field: str) -> str:
    """One caller-supplied number, checked before it becomes a URL path.

    These reach `httpx.URL` as path segments, and httpx resolves what it
    is given: `title="1#x"` fetches title 1 and the answer then reports
    it as the contents of "1#x", including in the arguments each row
    hands back — a wrong answer wearing a correct one's clothes.
    `title="../../vacode/1-500/"` walks to a different endpoint on the
    same host. The egress policy pins the host, so neither leaves the
    publisher, and neither is an answer to the question asked.
    """
    if not _NUMBER.fullmatch(value):
        raise InvalidQuery(
            f"{field} {value!r} is not a Code of Virginia number. They "
            "start with a digit and carry digits, dots, colons, letters "
            "and hyphens — '15.2', '22', '18.2-57'.")
    return value


def _entries(payload: Any, kind: str) -> list[CodeEntry]:
    """The publisher's three list shapes, flattened to one.

    Titles come back as a bare array. Chapters come back under
    `ChapterList`. Sections are nested two levels deeper, under articles
    and sub-parts, and the walk is over the leaves — a caller asking for a
    chapter's sections wants the sections, not the shape the publisher
    groups them in.
    """
    if kind == "title":
        rows = _rows(payload, list, "a list of titles")
    elif kind == "chapter":
        rows = _listing(_rows(payload, dict, "a title"), "ChapterList")
    else:
        rows = []
        for article in _listing(_rows(payload, dict, "a chapter"),
                                "ArticleList"):
            for subpart in _listing(_rows(article, dict, "an article"),
                                    "SubPartList"):
                rows += _listing(_rows(subpart, dict, "a sub-part"),
                                 "SectionList")
    fields = {"title": ("TitleNumber", "TitleName"),
              "chapter": ("ChapterNum", "ChapterName"),
              "section": ("SectionNumber", "SectionTitle")}[kind]
    out = []
    for row in rows:
        row = _rows(row, dict, f"a {kind}")
        out.append(CodeEntry(kind, row.get(fields[0]) or "",
                             row.get(fields[1]) or ""))
    return out


def _rows(payload: Any, want: type, described: str) -> Any:
    """`payload`, if it is the shape the publisher documents.

    An unexpected shape is an outage, not an empty Code. The publisher
    answering HTTP 200 with an error object, an interstitial, or a
    redesigned envelope would otherwise read as a title with no chapters
    in it — the exact confusion between "nothing there" and "could not
    look" that this project refuses everywhere else. A dict where a list
    belongs also raised `AttributeError` out of the tool, past the
    `CommonwealthError` the caller catches, so the whole call errored
    instead of recording one source's failure.
    """
    if not isinstance(payload, want):
        raise SourceUnavailable(
            f"the Code of Virginia API answered with "
            f"{type(payload).__name__}, not {described}. Treat this as "
            "the service having changed or failed, not as an empty "
            "branch of the Code.")
    return payload


def _listing(doc: dict, key: str) -> list:
    """The list under `key`, refusing a document that does not have one.

    The publisher always sends the key. A title it does not have comes
    back as `{"TitleNumber": null, ..., "ChapterList": []}`, and an
    unknown chapter the same way with `ArticleList` — verified against
    the live service on 2026-09-08. So an absent key is not the
    publisher's way of saying "empty", it is a document this parser does
    not recognise, and reading it as an empty branch of the Code would
    report `execution=complete` over a payload nobody understood. An
    explicit `null` is still treated as empty, because that is the
    publisher's own vocabulary for a branch with nothing under it.
    """
    if key not in doc:
        raise SourceUnavailable(
            f"the Code of Virginia API answered without {key!r}. The "
            "publisher sends that key even for a title or chapter it "
            "does not have, so this is a changed or failed service, not "
            "an empty branch of the Code.")
    value = doc[key]
    if value is None:
        return []
    return _rows(value, list, f"a list under {key!r}")


class VirginiaLawAdapter:
    version = "0.1.0"

    def __init__(self, fetcher: HtmlFetcher | None = None,
                 json_fetcher: Any = None) -> None:
        self._fetcher = fetcher
        # Separate from the HTML one so a test can replay the table of
        # contents without also having to answer section-page requests,
        # and the other way round.
        self._json_fetcher = json_fetcher

    def _fetcher_for(self, manifest: SourceManifest,
                     service_url: str) -> HtmlFetcher:
        if self._fetcher is not None:
            return self._fetcher
        return HttpFetcher(policy=egress_policy_for(manifest, service_url))

    def _json_fetcher_for(self, manifest: SourceManifest, api_url: str):
        if self._json_fetcher is not None:
            return self._json_fetcher
        return HttpFetcher(policy=egress_policy_for(manifest, api_url))

    async def get_section(self, manifest: SourceManifest,
                          citation: str) -> CodeSection | None:
        """`citation` is a Code of Virginia section number as the site
        spells it in URLs (e.g. "1-500", "18.2-57"). Returns None for a
        section the site doesn't have — never raises for that case, since
        an absent section is a normal, expected outcome, not a fault."""
        p = VirginiaLawParams.model_validate(
            manifest.adapter.model_dump(exclude={"type"}))
        fetcher = self._fetcher_for(manifest, p.service_url)
        url = f"{p.service_url}/{citation}/"
        html, final_url = await fetcher.fetch_html(url)
        parser = _SectionPageParser()
        parser.feed(html)
        log_source_call(manifest, "get_section", {"citation": citation},
                        1 if parser.found else 0)
        if not parser.found:
            return None
        heading = " ".join("".join(parser.heading_parts).split())
        return CodeSection(citation=citation, heading=heading,
                           paragraphs=parser.paragraphs,
                           source_url=final_url)

    async def browse(self, manifest: SourceManifest, title: str = "",
                     chapter: str = "") -> tuple[list[CodeEntry], str]:
        """The Code's own table of contents, one level at a time.

        Nothing narrows to the titles; a title narrows to its chapters; a
        title and a chapter narrow to that chapter's sections. Returns the
        entries and the URL they came from.

        This is a walk, not a search. The publisher runs no full-text
        operation (source-quirks.md § 18) and this does not simulate one
        by fetching everything and matching strings — that would be this
        project answering a question the source cannot, which is the
        failure `get_code_section` was named to avoid.
        """
        p = VirginiaLawParams.model_validate(
            manifest.adapter.model_dump(exclude={"type"}))
        if not p.api_url:
            raise SourceUnavailable(
                f"{manifest.id} declares no api_url, so the Code's table "
                "of contents cannot be read from it. Section lookup by "
                "citation is unaffected.")
        base = p.api_url.rstrip("/")
        if not title:
            op, kind = "CoVTitlesGetListOfJson", "title"
        elif not chapter:
            op, kind = (f"CoVChaptersGetListOfJson/"
                        f"{_segment(title, 'title')}", "chapter")
        else:
            op, kind = (f"CoVSectionsGetListOfJson/"
                        f"{_segment(title, 'title')}/"
                        f"{_segment(chapter, 'chapter')}", "section")
        url = f"{base}/{op}"
        fetcher = self._json_fetcher_for(manifest, p.api_url)
        payload = await fetcher.fetch_json(url, {})
        entries = _entries(payload, kind)
        log_source_call(manifest, "browse",
                        {"title": title, "chapter": chapter}, len(entries))
        return entries, url
