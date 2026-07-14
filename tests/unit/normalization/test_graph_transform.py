"""Parity tests for :class:`NormalizedGraphTransformer`.

The new transformer consumes a normalized ``InformationSchemaTable`` of flat
records (the shared ``information_schema_table`` fixture); the current
``BigQuerySchemaTransformer`` consumes pandas DataFrames. Both must produce
byte-for-byte identical graph nodes/relationships. ``test_parity_with_bigquery_transformer``
compares the two directly and will retire with the BigQuery transformer in PR 5;
the targeted tests pin each parity-critical rule against absolute values and are
the permanent regression guard once the old path is gone.
"""

import pandas as pd
import pytest

from neocarta.connectors.bigquery.schema.transform import BigQuerySchemaTransformer
from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.data_model.normalized import InformationSchemaTable
from neocarta.normalization.graph_transform import NormalizedGraphTransformer

# Identifiers of the shared ``information_schema_table`` fixture, used to build the
# equivalent old-path DataFrames and to assert on generated ids.
DATABASE = "test-project-id"
SCHEMA = "test_dataset"

CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "customers", "customer_id")
ORDERS_CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "orders", "customer_id")
VALUE_ID_1 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "1")
VALUE_ID_2 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "2")


def _bigquery_dataframes() -> dict[str, pd.DataFrame]:
    """Build the fixture as the DataFrames the BigQuery transformer consumes.

    The ``column_unique_values`` id columns are computed with the same id helpers
    the new transformer uses, mirroring how the BigQuery extractor pre-builds them,
    so the old precomputed ids equal the new generated ids.
    """
    return {
        "database_info": pd.DataFrame([{"project_id": DATABASE}]),
        "schema_info": pd.DataFrame(
            [
                {
                    "project_id": DATABASE,
                    "dataset_id": SCHEMA,
                    "description": "Test dataset description",
                }
            ]
        ),
        "table_info": pd.DataFrame(
            [
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "customers",
                    "description": "Customer table",
                },
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "orders",
                    "description": "Order table",
                },
            ]
        ),
        "column_info": pd.DataFrame(
            [
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "customers",
                    "column_name": "customer_id",
                    "data_type": "INT64",
                    "is_nullable": "NO",
                    "is_primary_key": True,
                    "is_foreign_key": False,
                    "description": "Customer ID",
                },
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "customers",
                    "column_name": "customer_name",
                    "data_type": "STRING",
                    "is_nullable": "YES",
                    "is_primary_key": False,
                    "is_foreign_key": False,
                    "description": "Customer name",
                },
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "orders",
                    "column_name": "order_id",
                    "data_type": "INT64",
                    "is_nullable": "NO",
                    "is_primary_key": True,
                    "is_foreign_key": False,
                    "description": "Order ID",
                },
                {
                    "table_catalog": DATABASE,
                    "table_schema": SCHEMA,
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "data_type": "INT64",
                    "is_nullable": "NO",
                    "is_primary_key": False,
                    "is_foreign_key": True,
                    "description": "Customer ID reference",
                },
            ]
        ),
        "column_references_info": pd.DataFrame(
            [
                {
                    "constraint_catalog": DATABASE,
                    "constraint_schema": SCHEMA,
                    "constraint_type": "FOREIGN KEY",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "referenced_table": "customers",
                    "referenced_column": "customer_id",
                },
                {
                    "constraint_catalog": DATABASE,
                    "constraint_schema": SCHEMA,
                    "constraint_type": "FOREIGN KEY",
                    "table_name": "orders",
                    "column_name": "customer_id",
                    "referenced_table": "orders",
                    "referenced_column": "customer_id",
                },
            ]
        ),
        "column_unique_values": pd.DataFrame(
            [
                {"unique_value": "1", "column_id": CUSTOMER_ID, "value_id": VALUE_ID_1},
                {"unique_value": "2", "column_id": CUSTOMER_ID, "value_id": VALUE_ID_2},
            ]
        ),
    }


@pytest.fixture
def old_transformer() -> BigQuerySchemaTransformer:
    """Run the DataFrame-based BigQuery transformer over the fixture."""
    frames = _bigquery_dataframes()
    transformer = BigQuerySchemaTransformer()
    transformer.transform_to_database_nodes(frames["database_info"])
    transformer.transform_to_schema_nodes(frames["schema_info"])
    transformer.transform_to_table_nodes(frames["table_info"])
    transformer.transform_to_column_nodes(frames["column_info"])
    transformer.transform_to_value_nodes(frames["column_unique_values"])
    transformer.transform_to_has_schema_relationships(frames["schema_info"])
    transformer.transform_to_has_table_relationships(frames["table_info"])
    transformer.transform_to_has_column_relationships(frames["column_info"])
    transformer.transform_to_references_relationships(frames["column_references_info"])
    transformer.transform_to_has_value_relationships(frames["column_unique_values"])
    return transformer


@pytest.fixture
def new_transformer(
    information_schema_table: InformationSchemaTable,
) -> NormalizedGraphTransformer:
    """Run the record-based normalized transformer over the equivalent fixture."""
    transformer = NormalizedGraphTransformer()
    transformer.transform(information_schema_table)
    return transformer


@pytest.mark.parametrize(
    "family",
    [
        "database_nodes",
        "schema_nodes",
        "table_nodes",
        "column_nodes",
        "value_nodes",
        "has_schema_relationships",
        "has_table_relationships",
        "has_column_relationships",
        "references_relationships",
        "has_value_relationships",
    ],
)
def test_parity_with_bigquery_transformer(
    family: str,
    old_transformer: BigQuerySchemaTransformer,
    new_transformer: NormalizedGraphTransformer,
) -> None:
    """Every node/relationship family equals the BigQuery transformer's output."""
    assert getattr(new_transformer, family) == getattr(old_transformer, family)


def test_nullable_decoded_from_yes_no(new_transformer: NormalizedGraphTransformer) -> None:
    """Raw ``"YES"``/``"NO"`` on the record become ``True``/``False`` on the column."""
    by_id = {column.id: column for column in new_transformer.column_nodes}
    assert by_id[CUSTOMER_ID].nullable is False
    assert (
        by_id[generate_column_id(DATABASE, SCHEMA, "customers", "customer_name")].nullable is True
    )


def test_primary_and_foreign_key_flags_are_bools(
    new_transformer: NormalizedGraphTransformer,
) -> None:
    """PK/FK flags pass through as concrete bools (record ``None`` default not hit)."""
    by_id = {column.id: column for column in new_transformer.column_nodes}
    assert by_id[CUSTOMER_ID].is_primary_key is True
    assert by_id[CUSTOMER_ID].is_foreign_key is False
    assert by_id[ORDERS_CUSTOMER_ID].is_primary_key is False
    assert by_id[ORDERS_CUSTOMER_ID].is_foreign_key is True


def test_real_foreign_key_edge_has_none_criteria(
    new_transformer: NormalizedGraphTransformer,
) -> None:
    """A real FK yields exactly one References edge (self-ref dropped) with no criteria."""
    references = new_transformer.references_relationships
    assert len(references) == 1
    reference = references[0]
    assert reference.source_column_id == ORDERS_CUSTOMER_ID
    assert reference.target_column_id == CUSTOMER_ID
    assert reference.criteria is None


def test_value_ids_from_generate_value_id(new_transformer: NormalizedGraphTransformer) -> None:
    """Value and HasValue ids match ``generate_value_id`` for the sampled values."""
    assert {value.id for value in new_transformer.value_nodes} == {VALUE_ID_1, VALUE_ID_2}
    assert {(rel.column_id, rel.value_id) for rel in new_transformer.has_value_relationships} == {
        (CUSTOMER_ID, VALUE_ID_1),
        (CUSTOMER_ID, VALUE_ID_2),
    }


def test_database_platform_and_service_uppercased(
    new_transformer: NormalizedGraphTransformer,
) -> None:
    """Lowercase record platform/service surface as GCP/BIGQUERY; description stays None."""
    database = new_transformer.database_nodes[0]
    assert database.id == "test_project_id"
    assert database.platform == "GCP"
    assert database.service == "BIGQUERY"
    assert database.description is None


def test_empty_container_yields_empty_families() -> None:
    """An empty container leaves every accessor as an empty list."""
    transformer = NormalizedGraphTransformer()
    transformer.transform(InformationSchemaTable())
    for family in (
        "database_nodes",
        "schema_nodes",
        "table_nodes",
        "column_nodes",
        "value_nodes",
        "has_schema_relationships",
        "has_table_relationships",
        "has_column_relationships",
        "references_relationships",
        "has_value_relationships",
    ):
        assert getattr(transformer, family) == []
