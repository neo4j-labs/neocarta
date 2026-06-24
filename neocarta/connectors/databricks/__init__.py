"""Databricks (managed Unity Catalog) connectors.

Currently provides the governance-tags sub-connector, which maps Unity Catalog
governed-tag *definitions* into the vendor-neutral governance-tag data model
(:GovernanceTagKey / :GovernanceTagValue). A future pyspark-based schema
sub-connector is planned and will ship in a separate optional-dependency extra so
the SQL-only tags connector never pulls Spark.
"""

from ...warnings import DatabricksTagsWarning
from .tags import DatabricksTagsConnector

__all__ = ["DatabricksTagsConnector", "DatabricksTagsWarning"]
