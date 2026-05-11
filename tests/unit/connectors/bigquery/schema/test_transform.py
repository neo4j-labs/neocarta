from neocarta.connectors.bigquery import BigQuerySchemaExtractor, BigQuerySchemaTransformer


def test_transform_to_database_nodes(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming database info to database nodes."""
    bigquery_transformer.transform_to_database_nodes(
        bigquery_extractor_with_cache.database_info, cache=True
    )

    assert len(bigquery_transformer.database_nodes) == 1
    assert bigquery_transformer.database_nodes[0].id == "test_project_id"
    assert bigquery_transformer.database_nodes[0].name == "test-project-id"
    assert bigquery_transformer.database_nodes[0].description is None


def test_transform_to_schema_nodes(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming schema info to schema nodes."""
    bigquery_transformer.transform_to_schema_nodes(
        bigquery_extractor_with_cache.schema_info, cache=True
    )

    assert len(bigquery_transformer.schema_nodes) == 1
    assert bigquery_transformer.schema_nodes[0].id == "test_project_id.test_dataset"
    assert bigquery_transformer.schema_nodes[0].name == "test_dataset"
    assert bigquery_transformer.schema_nodes[0].description == "Test dataset description"


def test_transform_to_table_nodes(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming table info to table nodes."""
    bigquery_transformer.transform_to_table_nodes(
        bigquery_extractor_with_cache.table_info, cache=True
    )

    assert len(bigquery_transformer.table_nodes) == 2
    assert bigquery_transformer.table_nodes[0].id == "test_project_id.test_dataset.customers"
    assert bigquery_transformer.table_nodes[0].name == "customers"
    assert bigquery_transformer.table_nodes[0].description == "Customer table"
    assert bigquery_transformer.table_nodes[1].id == "test_project_id.test_dataset.orders"
    assert bigquery_transformer.table_nodes[1].name == "orders"
    assert bigquery_transformer.table_nodes[1].description == "Order table"


def test_transform_to_column_nodes(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming column info to column nodes."""
    bigquery_transformer.transform_to_column_nodes(
        bigquery_extractor_with_cache.column_info, cache=True
    )

    assert len(bigquery_transformer.column_nodes) == 4
    assert (
        bigquery_transformer.column_nodes[0].id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert bigquery_transformer.column_nodes[0].name == "customer_id"
    assert bigquery_transformer.column_nodes[0].type == "INT64"
    assert bigquery_transformer.column_nodes[0].is_primary_key
    assert not bigquery_transformer.column_nodes[0].is_foreign_key
    assert (
        bigquery_transformer.column_nodes[1].id
        == "test_project_id.test_dataset.customers.customer_name"
    )
    assert bigquery_transformer.column_nodes[1].name == "customer_name"
    assert bigquery_transformer.column_nodes[1].type == "STRING"
    assert bigquery_transformer.column_nodes[2].id == "test_project_id.test_dataset.orders.order_id"
    assert bigquery_transformer.column_nodes[2].name == "order_id"
    assert (
        bigquery_transformer.column_nodes[3].id == "test_project_id.test_dataset.orders.customer_id"
    )
    assert bigquery_transformer.column_nodes[3].name == "customer_id"
    assert bigquery_transformer.column_nodes[3].is_foreign_key


def test_transform_to_value_nodes(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming value info to value nodes."""
    bigquery_transformer.transform_to_value_nodes(
        bigquery_extractor_with_cache.column_unique_values, cache=True
    )

    assert len(bigquery_transformer.value_nodes) == 2
    assert (
        bigquery_transformer.value_nodes[0].id
        == "test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b"
    )
    assert bigquery_transformer.value_nodes[0].value == "1"
    assert (
        bigquery_transformer.value_nodes[1].id
        == "test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c"
    )
    assert bigquery_transformer.value_nodes[1].value == "2"


def test_transform_to_has_schema_relationships(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming schema info to has schema relationships."""
    bigquery_transformer.transform_to_has_schema_relationships(
        bigquery_extractor_with_cache.schema_info, cache=True
    )

    assert len(bigquery_transformer.has_schema_relationships) == 1
    assert bigquery_transformer.has_schema_relationships[0].database_id == "test_project_id"
    assert (
        bigquery_transformer.has_schema_relationships[0].schema_id == "test_project_id.test_dataset"
    )


def test_transform_to_has_table_relationships(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming table info to has table relationships."""
    bigquery_transformer.transform_to_has_table_relationships(
        bigquery_extractor_with_cache.table_info, cache=True
    )

    assert len(bigquery_transformer.has_table_relationships) == 2
    assert (
        bigquery_transformer.has_table_relationships[0].schema_id == "test_project_id.test_dataset"
    )
    assert (
        bigquery_transformer.has_table_relationships[0].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer.has_table_relationships[1].schema_id == "test_project_id.test_dataset"
    )
    assert (
        bigquery_transformer.has_table_relationships[1].table_id
        == "test_project_id.test_dataset.orders"
    )


def test_transform_to_has_column_relationships(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming column info to has column relationships."""
    bigquery_transformer.transform_to_has_column_relationships(
        bigquery_extractor_with_cache.column_info, cache=True
    )

    assert len(bigquery_transformer.has_column_relationships) == 4
    assert (
        bigquery_transformer.has_column_relationships[0].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer.has_column_relationships[0].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer.has_column_relationships[1].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer.has_column_relationships[1].column_id
        == "test_project_id.test_dataset.customers.customer_name"
    )
    assert (
        bigquery_transformer.has_column_relationships[2].table_id
        == "test_project_id.test_dataset.orders"
    )
    assert (
        bigquery_transformer.has_column_relationships[2].column_id
        == "test_project_id.test_dataset.orders.order_id"
    )
    assert (
        bigquery_transformer.has_column_relationships[3].table_id
        == "test_project_id.test_dataset.orders"
    )
    assert (
        bigquery_transformer.has_column_relationships[3].column_id
        == "test_project_id.test_dataset.orders.customer_id"
    )


def test_transform_to_references_relationships(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming column references info to references relationships."""
    bigquery_transformer.transform_to_references_relationships(
        bigquery_extractor_with_cache.column_references_info, cache=True
    )

    assert len(bigquery_transformer.references_relationships) == 1
    assert (
        bigquery_transformer.references_relationships[0].source_column_id
        == "test_project_id.test_dataset.orders.customer_id"
    )
    assert (
        bigquery_transformer.references_relationships[0].target_column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )


def test_transform_to_references_relationships_drops_self_fk(
    bigquery_transformer: BigQuerySchemaTransformer,
):
    """Self-referencing FK rows (col -> same col on same table) must be dropped."""
    import pandas as pd

    column_references_info = pd.DataFrame(
        [
            # Bogus self-FK: orders.customer_id -> orders.customer_id
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "fk_bogus",
                "constraint_type": "FOREIGN KEY",
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_table": "orders",
                "referenced_column": "customer_id",
            },
            # Legitimate FK: orders.customer_id -> customers.customer_id
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "fk_customer",
                "constraint_type": "FOREIGN KEY",
                "table_name": "orders",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "referenced_table": "customers",
                "referenced_column": "customer_id",
            },
            # Legitimate self-reference across columns: employees.manager_id -> employees.employee_id
            {
                "constraint_catalog": "test-project-id",
                "constraint_schema": "test_dataset",
                "constraint_name": "fk_manager",
                "constraint_type": "FOREIGN KEY",
                "table_name": "employees",
                "column_name": "manager_id",
                "ordinal_position": 1,
                "referenced_table": "employees",
                "referenced_column": "employee_id",
            },
        ]
    )

    refs = bigquery_transformer.transform_to_references_relationships(
        column_references_info, cache=False
    )

    pairs = {(r.source_column_id, r.target_column_id) for r in refs}
    assert (
        "test_project_id.test_dataset.orders.customer_id",
        "test_project_id.test_dataset.orders.customer_id",
    ) not in pairs
    assert (
        "test_project_id.test_dataset.orders.customer_id",
        "test_project_id.test_dataset.customers.customer_id",
    ) in pairs
    assert (
        "test_project_id.test_dataset.employees.manager_id",
        "test_project_id.test_dataset.employees.employee_id",
    ) in pairs
    assert len(refs) == 2


def test_transform_to_has_value_relationships(
    bigquery_transformer: BigQuerySchemaTransformer,
    bigquery_extractor_with_cache: BigQuerySchemaExtractor,
):
    """Test transforming value info to has value relationships."""
    bigquery_transformer.transform_to_has_value_relationships(
        bigquery_extractor_with_cache.column_unique_values, cache=True
    )

    assert len(bigquery_transformer.has_value_relationships) == 2
    assert (
        bigquery_transformer.has_value_relationships[0].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer.has_value_relationships[0].value_id
        == "test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b"
    )
    assert (
        bigquery_transformer.has_value_relationships[1].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer.has_value_relationships[1].value_id
        == "test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c"
    )


def test_get_database_nodes(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test database_nodes property returns cached data."""
    assert len(bigquery_transformer_with_cache.database_nodes) == 1
    assert bigquery_transformer_with_cache.database_nodes[0].id == "test_project_id"
    assert bigquery_transformer_with_cache.database_nodes[0].name == "test-project-id"


def test_get_schema_nodes(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test schema_nodes property returns cached data."""
    assert len(bigquery_transformer_with_cache.schema_nodes) == 1
    assert bigquery_transformer_with_cache.schema_nodes[0].id == "test_project_id.test_dataset"
    assert bigquery_transformer_with_cache.schema_nodes[0].name == "test_dataset"


def test_get_table_nodes(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test table_nodes property returns cached data."""
    assert len(bigquery_transformer_with_cache.table_nodes) == 2
    assert (
        bigquery_transformer_with_cache.table_nodes[0].id
        == "test_project_id.test_dataset.customers"
    )
    assert bigquery_transformer_with_cache.table_nodes[0].name == "customers"
    assert (
        bigquery_transformer_with_cache.table_nodes[1].id == "test_project_id.test_dataset.orders"
    )
    assert bigquery_transformer_with_cache.table_nodes[1].name == "orders"


def test_get_column_nodes(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test column_nodes property returns cached data."""
    assert len(bigquery_transformer_with_cache.column_nodes) == 4
    assert (
        bigquery_transformer_with_cache.column_nodes[0].id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert bigquery_transformer_with_cache.column_nodes[0].name == "customer_id"
    assert (
        bigquery_transformer_with_cache.column_nodes[1].id
        == "test_project_id.test_dataset.customers.customer_name"
    )
    assert bigquery_transformer_with_cache.column_nodes[1].name == "customer_name"


def test_get_value_nodes(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test value_nodes property returns cached data."""
    assert len(bigquery_transformer_with_cache.value_nodes) == 2
    assert bigquery_transformer_with_cache.value_nodes[0].value == "1"
    assert bigquery_transformer_with_cache.value_nodes[1].value == "2"


def test_get_has_schema_relationships(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test has_schema_relationships property returns cached data."""
    assert len(bigquery_transformer_with_cache.has_schema_relationships) == 1
    assert (
        bigquery_transformer_with_cache.has_schema_relationships[0].database_id == "test_project_id"
    )
    assert (
        bigquery_transformer_with_cache.has_schema_relationships[0].schema_id
        == "test_project_id.test_dataset"
    )


def test_get_has_table_relationships(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test has_table_relationships property returns cached data."""
    assert len(bigquery_transformer_with_cache.has_table_relationships) == 2
    assert (
        bigquery_transformer_with_cache.has_table_relationships[0].schema_id
        == "test_project_id.test_dataset"
    )
    assert (
        bigquery_transformer_with_cache.has_table_relationships[0].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer_with_cache.has_table_relationships[1].schema_id
        == "test_project_id.test_dataset"
    )
    assert (
        bigquery_transformer_with_cache.has_table_relationships[1].table_id
        == "test_project_id.test_dataset.orders"
    )


def test_get_has_column_relationships(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test has_column_relationships property returns cached data."""
    assert len(bigquery_transformer_with_cache.has_column_relationships) == 4
    assert (
        bigquery_transformer_with_cache.has_column_relationships[0].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer_with_cache.has_column_relationships[0].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer_with_cache.has_column_relationships[1].table_id
        == "test_project_id.test_dataset.customers"
    )
    assert (
        bigquery_transformer_with_cache.has_column_relationships[1].column_id
        == "test_project_id.test_dataset.customers.customer_name"
    )


def test_get_references_relationships(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test references_relationships property returns cached data."""
    assert len(bigquery_transformer_with_cache.references_relationships) == 1
    assert (
        bigquery_transformer_with_cache.references_relationships[0].source_column_id
        == "test_project_id.test_dataset.orders.customer_id"
    )
    assert (
        bigquery_transformer_with_cache.references_relationships[0].target_column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )


def test_get_has_value_relationships(bigquery_transformer_with_cache: BigQuerySchemaTransformer):
    """Test has_value_relationships property returns cached data."""
    assert len(bigquery_transformer_with_cache.has_value_relationships) == 2
    assert (
        bigquery_transformer_with_cache.has_value_relationships[0].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer_with_cache.has_value_relationships[0].value_id
        == "test_project_id.test_dataset.customers.customer_id.c4ca4238a0b923820dcc509a6f75849b"
    )
    assert (
        bigquery_transformer_with_cache.has_value_relationships[1].column_id
        == "test_project_id.test_dataset.customers.customer_id"
    )
    assert (
        bigquery_transformer_with_cache.has_value_relationships[1].value_id
        == "test_project_id.test_dataset.customers.customer_id.c81e728d9d4c2f636f067f89cc14862c"
    )
