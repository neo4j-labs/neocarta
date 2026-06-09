"""Collibra Data Catalog connector for neocarta.

Provides two source sub-connectors over the Collibra Core REST API v2:

* :class:`~neocarta.connectors.collibra.schema.CollibraSchemaConnector` —
  physical-layer metadata (Database/Schema/Table/Column).
* :class:`~neocarta.connectors.collibra.glossary.CollibraGlossaryConnector` —
  business-glossary metadata (Glossary/Category/BusinessTerm) and TAGGED_WITH tags.
"""

from ...warnings import UnmappedCollibraAssetTypeWarning, UnresolvedCollibraParentWarning
from .client import CollibraClient
from .glossary import CollibraGlossaryConnector
from .schema import CollibraSchemaConnector

__all__ = [
    "CollibraClient",
    "CollibraGlossaryConnector",
    "CollibraSchemaConnector",
    "UnmappedCollibraAssetTypeWarning",
    "UnresolvedCollibraParentWarning",
]
