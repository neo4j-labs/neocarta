import pandas as pd

from neocarta.connectors.databricks.schema.extract import DatabricksSchemaExtractor
from neocarta.connectors.databricks.schema.transform import DatabricksSchemaTransformer

CATALOG = "test_catalog"
SCHEMA = "test_schema"


def test_transform_to_database_nodes(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform catalog info into Database nodes with Databricks platform/service."""
    databricks_transformer.transform_to_database_nodes(
        databricks_extractor_with_cache.database_info, cache=True
    )

    assert len(databricks_transformer.database_nodes) == 1
    node = databricks_transformer.database_nodes[0]
    assert node.id == CATALOG
    assert node.name == CATALOG
    assert node.description is None
    assert node.platform == "DATABRICKS"
    assert node.service == "UNITY_CATALOG"


def test_transform_to_schema_nodes(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform schema info into Schema nodes."""
    databricks_transformer.transform_to_schema_nodes(
        databricks_extractor_with_cache.schema_info, cache=True
    )

    assert len(databricks_transformer.schema_nodes) == 1
    assert databricks_transformer.schema_nodes[0].id == f"{CATALOG}.{SCHEMA}"
    assert databricks_transformer.schema_nodes[0].name == SCHEMA
    assert databricks_transformer.schema_nodes[0].description == "Test schema description"


def test_transform_to_table_nodes(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform table info into Table nodes."""
    databricks_transformer.transform_to_table_nodes(
        databricks_extractor_with_cache.table_info, cache=True
    )

    assert len(databricks_transformer.table_nodes) == 2
    assert databricks_transformer.table_nodes[0].id == f"{CATALOG}.{SCHEMA}.customers"
    assert databricks_transformer.table_nodes[0].name == "customers"
    assert databricks_transformer.table_nodes[1].id == f"{CATALOG}.{SCHEMA}.orders"


def test_transform_to_column_nodes(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform column info into Column nodes with type and key flags."""
    databricks_transformer.transform_to_column_nodes(
        databricks_extractor_with_cache.column_info, cache=True
    )

    nodes = databricks_transformer.column_nodes
    assert len(nodes) == 4
    assert nodes[0].id == f"{CATALOG}.{SCHEMA}.customers.customer_id"
    assert nodes[0].name == "customer_id"
    assert nodes[0].type == "INT"
    assert nodes[0].is_primary_key
    assert not nodes[0].is_foreign_key
    # 'NO' / 'YES' coerce to bool via pydantic.
    assert nodes[0].nullable is False
    assert nodes[1].nullable is True
    assert nodes[3].id == f"{CATALOG}.{SCHEMA}.orders.customer_id"
    assert nodes[3].is_foreign_key


def test_transform_to_value_nodes(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform value info into Value nodes."""
    databricks_transformer.transform_to_value_nodes(
        databricks_extractor_with_cache.column_unique_values, cache=True
    )

    assert len(databricks_transformer.value_nodes) == 2
    assert databricks_transformer.value_nodes[0].value == "1"
    assert databricks_transformer.value_nodes[1].value == "2"


def test_transform_to_has_schema_relationships(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform schema info into HAS_SCHEMA relationships."""
    databricks_transformer.transform_to_has_schema_relationships(
        databricks_extractor_with_cache.schema_info, cache=True
    )

    rels = databricks_transformer.has_schema_relationships
    assert len(rels) == 1
    assert rels[0].database_id == CATALOG
    assert rels[0].schema_id == f"{CATALOG}.{SCHEMA}"


def test_transform_to_has_table_relationships(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform table info into HAS_TABLE relationships."""
    databricks_transformer.transform_to_has_table_relationships(
        databricks_extractor_with_cache.table_info, cache=True
    )

    rels = databricks_transformer.has_table_relationships
    assert len(rels) == 2
    assert rels[0].schema_id == f"{CATALOG}.{SCHEMA}"
    assert rels[0].table_id == f"{CATALOG}.{SCHEMA}.customers"


def test_transform_to_has_column_relationships(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform column info into HAS_COLUMN relationships."""
    databricks_transformer.transform_to_has_column_relationships(
        databricks_extractor_with_cache.column_info, cache=True
    )

    rels = databricks_transformer.has_column_relationships
    assert len(rels) == 4
    assert rels[0].table_id == f"{CATALOG}.{SCHEMA}.customers"
    assert rels[0].column_id == f"{CATALOG}.{SCHEMA}.customers.customer_id"


def test_transform_to_references_relationships(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform FK references into REFERENCES relationships."""
    databricks_transformer.transform_to_references_relationships(
        databricks_extractor_with_cache.column_references_info, cache=True
    )

    rels = databricks_transformer.references_relationships
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{CATALOG}.{SCHEMA}.orders.customer_id"
    assert rels[0].target_column_id == f"{CATALOG}.{SCHEMA}.customers.customer_id"


def test_transform_self_table_fk_is_kept(
    databricks_transformer: DatabricksSchemaTransformer,
):
    """A self-referential-table FK across different columns produces an edge.

    (The Databricks referential query pairs FK->PK columns by ordinal and never
    collapses a column onto itself the way BigQuery's CONSTRAINT_COLUMN_USAGE join
    can, so there is no self-FK filtering.)
    """
    refs = pd.DataFrame(
        [
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": CATALOG,
                "table_schema": SCHEMA,
                "table_name": "employees",
                "column_name": "manager_id",
                "ordinal_position": 1,
                "referenced_catalog": CATALOG,
                "referenced_schema": SCHEMA,
                "referenced_table": "employees",
                "referenced_column": "employee_id",
            }
        ]
    )
    rels = databricks_transformer.transform_to_references_relationships(refs, cache=False)
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{CATALOG}.{SCHEMA}.employees.manager_id"
    assert rels[0].target_column_id == f"{CATALOG}.{SCHEMA}.employees.employee_id"


def test_transform_to_has_value_relationships(
    databricks_transformer: DatabricksSchemaTransformer,
    databricks_extractor_with_cache: DatabricksSchemaExtractor,
):
    """Transform value info into HAS_VALUE relationships."""
    databricks_transformer.transform_to_has_value_relationships(
        databricks_extractor_with_cache.column_unique_values, cache=True
    )

    rels = databricks_transformer.has_value_relationships
    assert len(rels) == 2
    assert rels[0].column_id == f"{CATALOG}.{SCHEMA}.customers.customer_id"


def test_transform_references_empty_frame(
    databricks_transformer: DatabricksSchemaTransformer,
):
    """An empty references frame (schema with no foreign keys) yields no edges, no crash."""
    empty = pd.DataFrame(
        columns=[
            "constraint_type",
            "table_catalog",
            "table_schema",
            "table_name",
            "column_name",
            "ordinal_position",
            "referenced_catalog",
            "referenced_schema",
            "referenced_table",
            "referenced_column",
        ]
    )
    assert databricks_transformer.transform_to_references_relationships(empty) == []


def test_transform_references_resolves_cross_schema_target(
    databricks_transformer: DatabricksSchemaTransformer,
):
    """A foreign key whose target table is in another schema resolves to that schema."""
    refs = pd.DataFrame(
        [
            {
                "constraint_type": "FOREIGN KEY",
                "table_catalog": CATALOG,
                "table_schema": "sales",
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_catalog": CATALOG,
                "referenced_schema": "core",
                "referenced_table": "customers",
                "referenced_column": "customer_id",
            }
        ]
    )
    rels = databricks_transformer.transform_to_references_relationships(refs, cache=False)
    assert len(rels) == 1
    assert rels[0].source_column_id == f"{CATALOG}.sales.orders.customer_id"
    # target uses the *referenced* schema 'core', not the FK's own 'sales'
    assert rels[0].target_column_id == f"{CATALOG}.core.customers.customer_id"


def test_transform_columns_empty_frame(
    databricks_transformer: DatabricksSchemaTransformer,
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
    assert databricks_transformer.transform_to_column_nodes(empty) == []


def test_transformer_cache_properties(
    databricks_transformer_with_cache: DatabricksSchemaTransformer,
):
    """The cached-property accessors return the populated node/relationship lists."""
    t = databricks_transformer_with_cache
    assert len(t.database_nodes) == 1
    assert t.database_nodes[0].service == "UNITY_CATALOG"
    assert len(t.schema_nodes) == 1
    assert len(t.table_nodes) == 2
    assert len(t.column_nodes) == 4
    assert len(t.value_nodes) == 2
    assert len(t.has_schema_relationships) == 1
    assert len(t.has_table_relationships) == 2
    assert len(t.has_column_relationships) == 4
    assert len(t.references_relationships) == 1
    assert len(t.has_value_relationships) == 2
