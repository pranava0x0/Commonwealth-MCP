"""Runtime context: the loaded registries and adapter instances tools run
against. Constructed once per process (server or CLI); tests construct it
with replay fetchers instead."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .adapters import ADAPTER_VERSIONS
from .adapters.arcgis import ArcGISAdapter
from .adapters.arcgis_geocode import ArcGISGeocodeAdapter
from .adapters.virginia_law import VirginiaLawAdapter
from .core.audit import AuditLog
from .core.jurisdiction import JurisdictionTable
from .core.registry import SourceRegistry
from .core.results import DiskResultStore, MemoryResultStore, ResultStore, prune_on_start

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = PROJECT_ROOT / "sources"

# The self-describing entry for the project's own jurisdiction table, used as
# provenance when a tool answers from project data rather than a government
# system (e.g. jurisdiction resolution, registry-gap determinations).
PROJECT_SOURCE = {
    "source_id": "commonwealth-jurisdictions",
    "publisher": "Commonwealth-MCP project (derived from Census TIGER, "
                 "verified 2026-08-27)",
    "system": "project-data",
    "dataset": "sources/jurisdictions",
}


@dataclass
class RuntimeContext:
    sources: SourceRegistry
    jurisdictions: JurisdictionTable
    arcgis: ArcGISAdapter
    geocoder: ArcGISGeocodeAdapter = field(
        default_factory=ArcGISGeocodeAdapter)
    virginia_law: VirginiaLawAdapter = field(default_factory=VirginiaLawAdapter)
    server_name: str = "commonwealth"
    server_version: str = __version__
    adapters: dict[str, str] = field(
        default_factory=lambda: dict(ADAPTER_VERSIONS))
    audit: AuditLog = field(default_factory=AuditLog)
    # Where payloads too large to return inline are kept (decision 0013).
    # Defaults to memory so importing this package never writes to a
    # user's disk; `load_context` gives a real process the disk backend.
    results: ResultStore = field(default_factory=MemoryResultStore)

    def classification_of(self, source_id: str) -> str:
        m = self.sources.get(source_id)
        return m.access.data_classification.value if m else "open"

    def has_sensitive_sources(self) -> bool:
        """Registry-wide, not per-call: used on the error path, where a
        failure can occur before it's known which source(s) a call would
        have reached. Conservative by construction — redacts error args
        whenever ANY sensitive_public source is registered, not only when
        this specific call's target was one."""
        return any(m.access.data_classification.value == "sensitive_public"
                  for m in self.sources.manifests.values())


def load_context(sources_dir: Path | None = None,
                 arcgis: ArcGISAdapter | None = None,
                 virginia_law: VirginiaLawAdapter | None = None,
                 geocoder: ArcGISGeocodeAdapter | None = None,
                 results: ResultStore | None = None) -> RuntimeContext:
    root = sources_dir or SOURCES_DIR
    store = results if results is not None else DiskResultStore()
    # 0013 asks for an expiry sweep and V1 has no scheduler, so it runs
    # when a process starts. The CLI and the server share the directory,
    # so a handle either of them minted resolves in the other.
    prune_on_start(store)
    return RuntimeContext(
        sources=SourceRegistry.load(root),
        jurisdictions=JurisdictionTable.load(root / "jurisdictions"),
        arcgis=arcgis or ArcGISAdapter(),
        geocoder=geocoder or ArcGISGeocodeAdapter(),
        virginia_law=virginia_law or VirginiaLawAdapter(),
        results=store)
