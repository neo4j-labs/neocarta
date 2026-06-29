"""Databricks (managed Unity Catalog) connectors.

Provides two sub-connectors over managed Databricks Unity Catalog:

- :class:`DatabricksSchemaConnector` — structural schema metadata
  (:Database/:Schema/:Table/:Column/:Value and their HAS_*/REFERENCES edges) read
  from a catalog's ``<catalog>.information_schema.*`` views over a Databricks SQL
  warehouse, using the in-process ``databricks-sql-connector`` (DB-API). No Spark
  or JDBC runtime is required — the lightweight, BigQuery-style path.
- :class:`DatabricksTagsConnector` — governed-tag *definitions* mapped into the
  vendor-neutral governance-tag data model (:GovernanceTagKey / :GovernanceTagValue)
  via the Databricks SDK (no SQL warehouse).

A Spark-based schema connector (for environments that prefer a Spark runtime and
the Neo4j Spark Connector) remains a separate, future option and would ship under
its own optional-dependency extra so this SQL-warehouse package never pulls Spark.
"""

from ...warnings import DatabricksTagsWarning
from .schema import DatabricksSchemaConnector
from .tags import DatabricksTagsConnector

__all__ = ["DatabricksSchemaConnector", "DatabricksTagsConnector", "DatabricksTagsWarning"]
