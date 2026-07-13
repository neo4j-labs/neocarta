"""Transform Databricks Unity Catalog schema metadata into graph nodes and relationships."""

from ...utils.rdbms_schema_transform import RdbmsSchemaTransformer


class DatabricksSchemaTransformer(RdbmsSchemaTransformer):
    """Transformer for Databricks Unity Catalog schema metadata.

    Maps ``information_schema`` frames onto the core RDBMS data model. Only the
    platform/service labels and the ``database_info`` column name (a catalog) differ
    from the shared :class:`RdbmsSchemaTransformer`; every mapping stage is inherited.
    """

    _PLATFORM = "DATABRICKS"
    _SERVICE = "UNITY_CATALOG"
    _DATABASE_COLUMN = "catalog"
