"""Typed error taxonomy (../../../design/architecture.md § 22, as revised 2026-08-26).

Emptiness and partial coverage are NOT errors — they are coverage dimensions
(envelope.Coverage). These classes exist only for conditions that prevent a
valid answer. Every message is written for the model: what failed, what it
means in government-data terms, what to try next. No stack traces, hostnames,
or credentials in messages.
"""
from __future__ import annotations


class CommonwealthError(Exception):
    """Base for all typed errors. `code` is the wire-stable class name."""

    code = "CommonwealthError"

    def model_message(self) -> str:
        return f"{self.code}: {self}"


class SourceUnavailable(CommonwealthError):
    code = "SourceUnavailable"


class RateLimited(CommonwealthError):
    code = "RateLimited"

    def __init__(self, msg: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(msg)
        self.retry_after_seconds = retry_after_seconds


class SourceSchemaChanged(CommonwealthError):
    code = "SourceSchemaChanged"


class InvalidQuery(CommonwealthError):
    code = "InvalidQuery"


class AmbiguousEntity(CommonwealthError):
    """Raised only when ambiguity cannot be expressed as candidates-in-data.

    The normal path (../../../design/architecture.md decision 0004) returns candidates in the envelope with
    requires_user_choice=true; this error is for malformed/contradictory input.
    """

    code = "AmbiguousEntity"


class UnsupportedJurisdiction(CommonwealthError):
    code = "UnsupportedJurisdiction"


class TermsRestricted(CommonwealthError):
    code = "TermsRestricted"


class EgressRefused(CommonwealthError):
    """A request violated the egress policy (design/security-and-data-handling.md § 2).

    Not in the ../../../design/architecture.md § 22 wire list: egress refusals are internal policy
    failures that surface to callers as SourceUnavailable with a policy note,
    never as an invitation to relax the policy from the tool surface.
    """

    code = "EgressRefused"
