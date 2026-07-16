"""Transform Snowflake schema metadata into graph nodes and relationships."""

from ...utils.rdbms_schema_transform import RdbmsSchemaTransformer


class SnowflakeSchemaTransformer(RdbmsSchemaTransformer):
    """Transformer for Snowflake schema metadata.

    Maps ``INFORMATION_SCHEMA`` frames onto the core RDBMS data model. Only the
    platform/service labels and the ``database_info`` column name differ from the
    shared :class:`RdbmsSchemaTransformer`; every mapping stage is inherited.
    """

    _PLATFORM = "SNOWFLAKE"
    _SERVICE = "SNOWFLAKE"
    _DATABASE_COLUMN = "database"
