"""Databricks Unity Catalog schema connector.

Importing this package is light: ``DatabricksSparkSchemaConnector`` is always
available, and the Spark-dependent entry points (``run_ingest``,
``SparkIngestSettings``) are imported lazily so the package can be imported
without the ``databricks-spark`` optional dependencies installed.
"""

from neocarta.connectors.databricks.connector import DatabricksSparkSchemaConnector

__all__ = ["DatabricksSparkSchemaConnector"]
