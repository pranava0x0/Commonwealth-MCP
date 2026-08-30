"""Adapters. Importing this package registers each adapter's params model
with the core registry so manifest validation can check adapter blocks."""

from . import arcgis  # noqa: F401  (registers ArcGISParams)
from . import inventory  # noqa: F401  (registers InventoryOnlyParams)
from . import virginia_law  # noqa: F401  (registers VirginiaLawParams)

# `none` has no adapter class and therefore no version: it names the absence
# of an endpoint, and a version string would imply code that can run.
ADAPTER_VERSIONS = {"arcgis": arcgis.ArcGISAdapter.version,
                    "virginia_law": virginia_law.VirginiaLawAdapter.version}
