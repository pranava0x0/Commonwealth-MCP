"""Virginia Law (law.lis.virginia.gov) adapter: Code of Virginia section
lookup by citation.

No JSON/XML API is reachable without registering for an LIS API key
(the GitHub issues, civic vertical note); the public website itself is plain,
anonymous, server-rendered HTML with a stable structure, so this adapter
reads that directly rather than waiting on a credential this project
can't self-register for. A missing section is not a 404 — the site
302-redirects to the enclosing title's chapter listing, a page with a
different, detectable shape (design/provenance-envelope.md § 2: never
guess, detect the real signal).
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.registry import SourceManifest, register_adapter_params
from .base import HtmlFetcher, HttpFetcher, egress_policy_for, log_source_call


class VirginiaLawParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_url: str  # e.g. https://law.lis.virginia.gov/vacode


register_adapter_params("virginia_law", VirginiaLawParams)


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


class VirginiaLawAdapter:
    version = "0.1.0"

    def __init__(self, fetcher: HtmlFetcher | None = None) -> None:
        self._fetcher = fetcher

    def _fetcher_for(self, manifest: SourceManifest,
                     service_url: str) -> HtmlFetcher:
        if self._fetcher is not None:
            return self._fetcher
        return HttpFetcher(policy=egress_policy_for(manifest, service_url))

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
