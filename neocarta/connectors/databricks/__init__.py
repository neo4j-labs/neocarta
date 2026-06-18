"""Databricks (managed Unity Catalog) connectors.

Currently provides the governed-tags business-glossary sub-connector. A future
pyspark-based schema sub-connector is planned and will ship in a separate
optional-dependency extra so the SQL-only glossary connector never pulls Spark.
"""

from ...warnings import DatabricksGlossaryWarning
from .glossary import DatabricksGlossaryConnector

__all__ = ["DatabricksGlossaryConnector", "DatabricksGlossaryWarning"]
