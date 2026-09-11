"""Runtime context: the loaded registries and adapter instances tools run
against. Constructed once per process (server or CLI); tests construct it
with replay fetchers instead."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .adapters import ADAPTER_VERSIONS
from .adapters.agenda_platform import AgendaPlatformAdapter
from .adapters.arcgis import ArcGISAdapter
from .adapters.arcgis_geocode import ArcGISGeocodeAdapter
from .adapters.virginia_law import VirginiaLawAdapter
from .core.audit import AuditLog
from .core.jurisdiction import JurisdictionTable
from .core.registry import SourceRegistry
from .core.results import DiskResultStore, MemoryResultStore, ResultStore, prune_on_start

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    """Where the source registry, the jurisdiction table and the skills are.

    Two layouts, because this package is used both ways. In a checkout
    they sit at the repo root beside `src/`, which is what `PROJECT_ROOT`
    finds. In an installed wheel there is no repo root above
    `site-packages/commonwealth/`, and resolving two directories up from
    the module pointed at the interpreter's own `lib/`, so every command
    died at startup on `missing capability vocabulary:
    .../lib/python3.12/sources/capabilities.yaml`. The wheel carries the
    data inside the package instead, and this prefers that copy.

    The checkout wins where there is one. `pip install -e .` materialises
    the bundled copy into site-packages as well, and that copy is frozen
    at install time: preferring it would have served yesterday's
    manifests to a developer editing today's, silently and with no error
    to notice. A repo root with a `sources/` directory beside `src/` is
    the unambiguous sign of a checkout, so it is checked first.

    `pyproject.toml`'s `force-include` block is the other half; a test
    asserts the two agree.
    """
    if (PROJECT_ROOT / "sources").is_dir():
        return PROJECT_ROOT
    bundled = Path(__file__).resolve().parent / "_data"
    return bundled if bundled.is_dir() else PROJECT_ROOT


DATA_ROOT = _data_root()
SOURCES_DIR = DATA_ROOT / "sources"

# Skills are the one directory whose checkout path is not its wheel path.
# They live inside the plugin bundle that installs them alongside the
# server (GitHub issue #53), because a client discovers a plugin's skills
# by convention, in a `skills/` directory under the plugin root. The wheel
# force-includes that same directory flat under `_data/`, so there is one
# copy in the repo and one in the package, and never a third to go stale.
# The checkout wins where there is one, for the reason `_data_root()`
# gives: an editable install's bundled copy is frozen at install time.
_CHECKOUT_SKILLS = PROJECT_ROOT / "plugins" / "commonwealth-mcp" / "skills"
SKILLS_DIR = (_CHECKOUT_SKILLS if _CHECKOUT_SKILLS.is_dir()
              else DATA_ROOT / "skills")

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
    agendas: AgendaPlatformAdapter = field(
        default_factory=AgendaPlatformAdapter)
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
                 agendas: AgendaPlatformAdapter | None = None,
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
        agendas=agendas or AgendaPlatformAdapter(),
        results=store)
