"""Find candidate publisher services in the Virginia catalog without contacting them."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..adapters.base import Fetcher, HttpFetcher, egress_policy_for
from ..core.errors import InvalidQuery, SourceSchemaChanged, SourceUnavailable, TermsRestricted
from ..core.registry import AutomationStatus, DeclaredState
from ..runtime import RuntimeContext

# A catalog search is a contributor operation, not a domain source activation.
PORTAL = "https://data.virginia.gov/api/3/action/package_search"
_SERVICE = re.compile(r"/(?:FeatureServer|MapServer)(?:/([0-9]+))?/?$", re.I)
_KINDS = ["layer", "service", "link"]
_COVERAGE = ["local_gap", "local_source", "unassessed"]
_PAGE_SORT = "score desc, metadata_modified desc, id asc"


def _text(value: object) -> str:
    # Catalog labels are external text, also when printed to a terminal.
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


def _resource_kind(url: object) -> str | None:
    if (not isinstance(url, str) or not url or "\\" in url
            or any(not c.isprintable() or c.isspace() for c in url)):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
            return None
    except ValueError:
        return None
    match = _SERVICE.search(parts.path)
    if not match:
        return "link"
    return "layer" if match.group(1) is not None else "service"


def _locality(ctx: RuntimeContext, publisher: str) -> str | None:
    label = re.sub(r"\s+-\s+GIS Portal$", "", publisher, flags=re.I)
    label = re.sub(r"^City of (.+)$", r"\1 City", label, flags=re.I)
    label = re.sub(r"^County of (.+)$", r"\1 County", label, flags=re.I)
    label = re.sub(r"^Town of (.+)$", r"\1 (town)", label, flags=re.I)
    hit = ctx.jurisdictions.resolve(label).resolved if label else None
    return hit.id if hit and hit.kind.value in {"county", "independent-city", "town"} else None


def _coverage(ctx: RuntimeContext, title: str, locality: str | None) -> tuple[str | None, str]:
    # A zoning overlay, variance application or parcel centroid cannot
    # fill the gap for a base district or parcel polygon on its title alone.
    name = title.casefold()
    if locality:
        gov = ctx.jurisdictions.get(locality)
        short = re.sub(r" (?:city|county|\(town\))$", "", gov.name.casefold())
        for prefix in (gov.name.casefold(), short):
            name = name.removeprefix(prefix + " ")
    capability = None
    if re.fullmatch(r"(?:base )?zoning(?: districts?| boundaries| map)?", name):
        capability = "zoning.lookup"
    elif re.fullmatch(r"(?:tax )?parcels?(?: boundaries| polygons)?", name):
        capability = "parcel.lookup"
    if not capability or not locality:
        return capability, "unassessed"
    return capability, ("local_source" if ctx.sources.select(capability, [locality]) else "local_gap")


async def discover(ctx: RuntimeContext, query: str, limit: int = 20, start: int = 0,
                   fetcher: Fetcher | None = None) -> dict:
    query = query.strip()
    if not query or len(query) > 200 or not 1 <= limit <= 50 or start < 0:
        raise InvalidQuery("Use 1–200 query characters, a limit of 1–50 datasets, and a nonnegative start.")
    manifest = ctx.sources.get("va-open-data-portal")
    if manifest is None or manifest.adapter.model_dump().get("discovery_url") != PORTAL:
        raise SourceUnavailable("The reviewed Virginia Open Data Portal endpoint is not configured.")
    if (manifest.lifecycle.declared_state == DeclaredState.retired or
            manifest.access.automation_status not in {AutomationStatus.public_api, AutomationStatus.permitted}
            or not manifest.access.terms_reviewed_at):
        raise TermsRestricted("The portal manifest does not permit catalog API searches.")
    if fetcher is None:
        fetcher = HttpFetcher(policy=egress_policy_for(manifest, PORTAL))
    response = await fetcher.fetch_json(PORTAL, {"q": query, "rows": limit, "start": start,
                                                 "sort": _PAGE_SORT})
    if response.get("success") is not True:
        raise SourceUnavailable("The Virginia Open Data Portal did not complete this search.")
    result = response.get("result")
    if (not isinstance(result, dict) or not isinstance(result.get("results"), list)
            or type(result.get("count")) is not int or result["count"] < 0):
        raise SourceSchemaChanged("The portal did not return its dataset list and total.")
    datasets = result["results"]
    candidates = []
    for row in datasets:
        if not isinstance(row, dict) or not isinstance(row.get("resources"), list):
            raise SourceSchemaChanged("The portal returned a dataset without its resource list.")
        org = row.get("organization")
        publisher = _text(org.get("title")) if isinstance(org, dict) else ""
        title = _text(row.get("title"))
        locality = _locality(ctx, publisher)
        capability, coverage = _coverage(ctx, title, locality)
        links = {}
        for resource in row["resources"]:
            if isinstance(resource, dict) and (kind := _resource_kind(resource.get("url"))):
                links.setdefault(resource["url"], kind)
        # Prefer the actual ArcGIS targets to alternative downloads of the
        # same dataset. Otherwise retain one catalog link as a manual lead.
        services = [(url, k) for url, k in links.items() if k != "link"]
        for url, kind in services or list(links.items())[:1]:
            candidates.append(dict(title=title, publisher=publisher, jurisdiction=locality,
                                   capability_hint=capability, local_coverage=coverage,
                                   resource_url=url, kind=kind, catalog_modified=_text(row.get("metadata_modified")) or None))
    candidates.sort(key=lambda c: (_COVERAGE.index(c["local_coverage"]), _KINDS.index(c["kind"])))
    end = start + len(datasets)
    return dict(total_datasets=result["count"], datasets_examined=len(datasets),
                next_start=end if datasets and end < result["count"] else None, candidates=candidates)
