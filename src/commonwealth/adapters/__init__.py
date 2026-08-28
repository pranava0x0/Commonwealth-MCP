"""Adapters. Importing this package registers each adapter's params model
with the core registry so manifest validation can check adapter blocks."""

from . import arcgis  # noqa: F401  (registers ArcGISParams)
from . import virginia_law  # noqa: F401  (registers VirginiaLawParams)

ADAPTER_VERSIONS = {"arcgis": arcgis.ArcGISAdapter.version,
                    "virginia_law": virginia_law.VirginiaLawAdapter.version}
