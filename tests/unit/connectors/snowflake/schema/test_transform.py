import pandas as pd

from neocarta.connectors.snowflake.schema.extract import SnowflakeSchemaExtractor
from neocarta.connectors.snowflake.schema.transform import SnowflakeSchemaTransformer

DATABASE = "test_database"
SCHEMA = "test_schema"


def test_transform_to_database_nodes(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform database info into Database nodes with Snowflake platform/service."""
    snowflake_transformer.transform_to_database_nodes(
        snowflake_extractor_with_cache.database_info, cache=True
    )

    assert len(snowflake_transformer.database_nodes) == 1
    node = snowflake_transformer.database_nodes[0]
    assert node.id == DATABASE
    assert node.name == DATABASE
    assert node.description is None
    assert node.platform == "SNOWFLAKE"
    assert node.service == "SNOWFLAKE"


def test_transform_to_schema_nodes(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform schema info into Schema nodes."""
    snowflake_transformer.transform_to_schema_nodes(
        snowflake_extractor_with_cache.schema_info, cache=True
    )

    assert len(snowflake_transformer.schema_nodes) == 1
    assert snowflake_transformer.schema_nodes[0].id == f"{DATABASE}.{SCHEMA}"
    assert snowflake_transformer.schema_nodes[0].name == SCHEMA
    assert snowflake_transformer.schema_nodes[0].description == "Test schema description"


def test_transform_to_table_nodes(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform table info into Table nodes."""
    snowflake_transformer.transform_to_table_nodes(
        snowflake_extractor_with_cache.table_info, cache=True
    )

    assert len(snowflake_transformer.table_nodes) == 2
    assert snowflake_transformer.table_nodes[0].id == f"{DATABASE}.{SCHEMA}.customers"
    assert snowflake_transformer.table_nodes[0].name == "customers"
    assert snowflake_transformer.table_nodes[1].id == f"{DATABASE}.{SCHEMA}.orders"


def test_transform_to_column_nodes(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform column info into Column nodes with type and key flags."""
    snowflake_transformer.transform_to_column_nodes(
        snowflake_extractor_with_cache.column_info, cache=True
    )

    nodes = snowflake_transformer.column_nodes
    assert len(nodes) == 4
    assert nodes[0].id == f"{DATABASE}.{SCHEMA}.customers.customer_id"
    assert nodes[0].name == "customer_id"
    assert nodes[0].type == "NUMBER"
    assert nodes[0].is_primary_key
    assert not nodes[0].is_foreign_key
    # 'NO' / 'YES' coerce to bool via pydantic.
    assert nodes[0].nullable is False
    assert nodes[1].nullable is True
    assert nodes[3].id == f"{DATABASE}.{SCHEMA}.orders.customer_id"
    assert nodes[3].is_foreign_key


def test_transform_to_value_nodes(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform value info into Value nodes."""
    snowflake_transformer.transform_to_value_nodes(
        snowflake_extractor_with_cache.column_unique_values, cache=True
    )

    assert len(snowflake_transformer.value_nodes) == 2
    assert snowflake_transformer.value_nodes[0].value == "1"
    assert snowflake_transformer.value_nodes[1].value == "2"


def test_transform_to_has_schema_relationships(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform schema info into HAS_SCHEMA relationships."""
    snowflake_transformer.transform_to_has_schema_relationships(
        snowflake_extractor_with_cache.schema_info, cache=True
    )

    rels = snowflake_transformer.has_schema_relationships
    assert len(rels) == 1
    assert rels[0].database_id == DATABASE
    assert rels[0].schema_id == f"{DATABASE}.{SCHEMA}"


def test_transform_to_has_table_relationships(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform table info into HAS_TABLE relationships."""
    snowflake_transformer.transform_to_has_table_relationships(
        snowflake_extractor_with_cache.table_info, cache=True
    )

    rels = snowflake_transformer.has_table_relationships
    assert len(rels) == 2
    assert rels[0].schema_id == f"{DATABASE}.{SCHEMA}"
    assert rels[0].table_id == f"{DATABASE}.{SCHEMA}.customers"


def test_transform_to_has_column_relationships(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform column info into HAS_COLUMN relationships."""
    snowflake_transformer.transform_to_has_column_relationships(
        snowflake_extractor_with_cache.column_info, cache=True
    )

    rels = snowflake_transformer.has_column_relationships
    assert len(rels) == 4
    assert rels[0].table_id == f"{DATABASE}.{SCHEMA}.customers"
    assert rels[0].column_id == f"{DATABASE}.{SCHEMA}.customers.customer_id"


def test_transform_to_references_relationships(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform FK references into REFERENCES relationships."""
    snowflake_transformer.transform_to_references_relationships(
        snowflake_extractor_with_cache.column_references_info, cache=True
    )

    rels = snowflake_transformer.references_relationships
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{DATABASE}.{SCHEMA}.orders.customer_id"
    assert rels[0].target_column_id == f"{DATABASE}.{SCHEMA}.customers.customer_id"


def test_transform_self_table_fk_is_kept(
    snowflake_transformer: SnowflakeSchemaTransformer,
):
    """A self-referential-table FK across different columns produces an edge.

    (SHOW IMPORTED KEYS pairs FK->PK columns directly and never collapses a column
    onto itself the way BigQuery's CONSTRAINT_COLUMN_USAGE join can, so there is no
    self-FK filtering — matching the Databricks connector.)
    """
    refs = pd.DataFrame(
        [
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": DATABASE,
                "table_schema": SCHEMA,
                "table_name": "employees",
                "column_name": "manager_id",
                "referenced_catalog": DATABASE,
                "referenced_schema": SCHEMA,
                "referenced_table": "employees",
                "referenced_column": "employee_id",
            }
        ]
    )
    rels = snowflake_transformer.transform_to_references_relationships(refs, cache=False)
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{DATABASE}.{SCHEMA}.employees.manager_id"
    assert rels[0].target_column_id == f"{DATABASE}.{SCHEMA}.employees.employee_id"


def test_transform_to_has_value_relationships(
    snowflake_transformer: SnowflakeSchemaTransformer,
    snowflake_extractor_with_cache: SnowflakeSchemaExtractor,
):
    """Transform value info into HAS_VALUE relationships."""
    snowflake_transformer.transform_to_has_value_relationships(
        snowflake_extractor_with_cache.column_unique_values, cache=True
    )

    rels = snowflake_transformer.has_value_relationships
    assert len(rels) == 2
    assert rels[0].column_id == f"{DATABASE}.{SCHEMA}.customers.customer_id"


def test_transform_references_empty_frame(
    snowflake_transformer: SnowflakeSchemaTransformer,
):
    """An empty references frame (schema with no foreign keys) yields no edges, no crash."""
    empty = pd.DataFrame(
        columns=[
            "constraint_type",
            "table_catalog",
            "table_schema",
            "table_name",
            "column_name",
            "referenced_catalog",
            "referenced_schema",
            "referenced_table",
            "referenced_column",
        ]
    )
    assert snowflake_transformer.transform_to_references_relationships(empty) == []


def test_transform_references_columnless_frame(
    snowflake_transformer: SnowflakeSchemaTransformer,
):
    """A bare empty frame carrying no ``constraint_type`` column yields no edges, no KeyError."""
    assert snowflake_transformer.transform_to_references_relationships(pd.DataFrame()) == []


def test_transform_references_resolves_cross_schema_target(
    snowflake_transformer: SnowflakeSchemaTransformer,
):
    """A foreign key whose target table is in another schema resolves to that schema."""
    refs = pd.DataFrame(
        [
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": DATABASE,
                "table_schema": "sales",
                "table_name": "orders",
                "column_name": "customer_id",
                "referenced_catalog": DATABASE,
                "referenced_schema": "core",
                "referenced_table": "customers",
                "referenced_column": "customer_id",
            }
        ]
    )
    rels = snowflake_transformer.transform_to_references_relationships(refs, cache=False)
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{DATABASE}.sales.orders.customer_id"
    # target uses the *referenced* schema 'core', not the FK's own 'sales'
    assert rels[0].target_column_id == f"{DATABASE}.core.customers.customer_id"


def test_transform_columns_empty_frame(
    snowflake_transformer: SnowflakeSchemaTransformer,
):
    """An empty columns frame (schema with no tables) yields no nodes, no crash."""
    empty = pd.DataFrame(
        columns=[
            "table_catalog",
            "table_schema",
            "table_name",
            "column_name",
            "is_nullable",
            "data_type",
            "description",
            "is_primary_key",
            "is_foreign_key",
        ]
    )
    assert snowflake_transformer.transform_to_column_nodes(empty) == []


def test_transformer_cache_properties(
    snowflake_transformer_with_cache: SnowflakeSchemaTransformer,
):
    """The cached-property accessors return the populated node/relationship lists."""
    t = snowflake_transformer_with_cache
    assert len(t.database_nodes) == 1
    assert t.database_nodes[0].service == "SNOWFLAKE"
    assert len(t.schema_nodes) == 1
    assert len(t.table_nodes) == 2
    assert len(t.column_nodes) == 4
    assert len(t.value_nodes) == 2
    assert len(t.has_schema_relationships) == 1
    assert len(t.has_table_relationships) == 2
    assert len(t.has_column_relationships) == 4
    assert len(t.references_relationships) == 1
    assert len(t.has_value_relationships) == 2
