"""Databricks (managed Unity Catalog) connectors.

Currently provides the governance-tags sub-connector, which maps Unity Catalog
governed-tag *definitions* into the vendor-neutral governance-tag data model
(:GovernanceTagKey / :GovernanceTagValue) via the Databricks SDK (no SQL warehouse
or Spark). A future pyspark-based schema sub-connector is planned and will ship in
a separate optional-dependency extra so this warehouse-free tags connector never
pulls Spark.
"""

from ...warnings import DatabricksTagsWarning
from .tags import DatabricksTagsConnector

__all__ = ["DatabricksTagsConnector", "DatabricksTagsWarning"]
