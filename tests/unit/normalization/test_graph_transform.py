"""Targeted regression tests for :class:`NormalizedGraphTransformer`.

The transformer consumes a normalized ``InformationSchemaTable`` of flat records
(the shared ``information_schema_table`` fixture) and produces the graph nodes and
relationships. Each test pins a parity-critical rule against absolute values, so
together they are the permanent regression guard for the shared pipeline.
"""

import pytest

from neocarta.connectors.utils.generate_id import generate_column_id, generate_value_id
from neocarta.data_model.normalized import InformationSchemaTable
from neocarta.normalization.graph_transform import NormalizedGraphTransformer

# Identifiers of the shared ``information_schema_table`` fixture, used to assert on
# generated ids.
DATABASE = "test-project-id"
SCHEMA = "test_dataset"

CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "customers", "customer_id")
ORDERS_CUSTOMER_ID = generate_column_id(DATABASE, SCHEMA, "orders", "customer_id")
VALUE_ID_1 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "1")
VALUE_ID_2 = generate_value_id(DATABASE, SCHEMA, "customers", "customer_id", "2")


@pytest.fixture
def new_transformer(
    information_schema_table: InformationSchemaTable,
) -> NormalizedGraphTransformer:
    """Run the record-based normalized transformer over the equivalent fixture."""
    transformer = NormalizedGraphTransformer()
    transformer.transform(information_schema_table)
    return transformer


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
