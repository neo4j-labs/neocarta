"""Connector-level parity test for the BigQuery schema normalization chain.

Drives the shared pipeline from real :class:`BigQuerySchemaExtractor` output —
``build_bigquery_information_schema_normalizer(extractor).normalize()`` then
``NormalizedGraphTransformer().transform(...)`` — and asserts the ten produced
node/relationship families equal the frozen graph the connector emitted before
the switch to the shared normalizer (PR #271).

Per-rule regression guards for the transform live in
``tests/unit/normalization/test_graph_transform.py``; this test's unique job is the
seam from real extractor output. Expected ids are written as literals rather than
generated, so the oracle also guards the id helpers against regression.
"""

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from neocarta.data_model.instance import HasValue, Value
from neocarta.data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from neocarta.normalization.graph_transform import NormalizedGraphTransformer
from neocarta.normalization.information_schema.bigquery import (
    build_bigquery_information_schema_normalizer,
)

# Frozen graph the bespoke BigQuerySchemaTransformer emitted for the
# customers/orders fixture (one foreign key, two sampled values). ids are the
# deterministic values the id helpers produce for these name-parts; value ids
# append the md5 of the sampled value.
_EXPECTED_GRAPH = {
    "database_nodes": [
        Database(
            id="test_project_id",
            name="test-project-id",
            platform="GCP",
            service="BIGQUERY",
            description=None,
        )
    ],
    "schema_nodes": [
        Schema(
            id="test_project_id.test_dataset",
            name="test_dataset",
            description="Test dataset description",
        )
    ],
    "table_nodes": [
        Table(
            id="test_project_id.test_dataset.customers",
            name="customers",
            description="Customer table",
        ),
        Table(
            id="test_project_id.test_dataset.orders",
            name="orders",
            description="Order table",
        ),
    ],
    "column_nodes": [
        Column(
            id="test_project_id.test_dataset.customers.customer_id",
            name="customer_id",
            description="Customer ID",
            type="INT64",
            nullable=False,
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.customers.customer_name",
            name="customer_name",
            description="Customer name",
            type="STRING",
            nullable=True,
            is_primary_key=False,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.orders.order_id",
            name="order_id",
            description="Order ID",
            type="INT64",
            nullable=False,
            is_primary_key=True,
            is_foreign_key=False,
        ),
        Column(
            id="test_project_id.test_dataset.orders.customer_id",
            name="customer_id",
            description="Customer ID reference",
            type="INT64",
            nullable=False,
            is_primary_key=False,
            is_foreign_key=True,
        ),
    ],
    "value_nodes": [
        Value(
            id="test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
            value="1",
        ),
        Value(
            id="test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
            value="2",
        ),
    ],
    "has_schema_relationships": [
        HasSchema(database_id="test_project_id", schema_id="test_project_id.test_dataset")
    ],
    "has_table_relationships": [
        HasTable(
            schema_id="test_project_id.test_dataset",
            table_id="test_project_id.test_dataset.customers",
        ),
        HasTable(
            schema_id="test_project_id.test_dataset",
            table_id="test_project_id.test_dataset.orders",
        ),
    ],
    "has_column_relationships": [
        HasColumn(
            table_id="test_project_id.test_dataset.customers",
            column_id="test_project_id.test_dataset.customers.customer_id",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.customers",
            column_id="test_project_id.test_dataset.customers.customer_name",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.orders",
            column_id="test_project_id.test_dataset.orders.order_id",
        ),
        HasColumn(
            table_id="test_project_id.test_dataset.orders",
            column_id="test_project_id.test_dataset.orders.customer_id",
        ),
    ],
    "references_relationships": [
        References(
            source_column_id="test_project_id.test_dataset.orders.customer_id",
            target_column_id="test_project_id.test_dataset.customers.customer_id",
            criteria=None,
        )
    ],
    "has_value_relationships": [
        HasValue(
            column_id="test_project_id.test_dataset.customers.customer_id",
            value_id="test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b",
        ),
        HasValue(
            column_id="test_project_id.test_dataset.customers.customer_id",
            value_id="test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c",
        ),
    ],
}


def test_normalized_chain_reproduces_connector_graph(
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
) -> None:
    """Retriever + spec + graph-transform reproduce the pre-switch connector graph."""
    normalizer = build_bigquery_information_schema_normalizer(bigquery_extractor_with_cache)
    transformer = NormalizedGraphTransformer()
    transformer.transform(normalizer.normalize())

    for family, expected in _EXPECTED_GRAPH.items():
        assert getattr(transformer, family) == expected, family
