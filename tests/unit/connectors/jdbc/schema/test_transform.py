"""Unit tests for the JDBC schema transformer."""


def test_transform_to_database_nodes(transformer, extractor_with_cache):
    """The single database row becomes one Database node."""
    nodes = transformer.transform_to_database_nodes(extractor_with_cache.database_info)
    assert len(nodes) == 1
    assert nodes[0].id == "neocarta_test"
    assert nodes[0].name == "neocarta_test"


def test_transform_to_schema_nodes_unfiltered(transformer, extractor_with_cache):
    """Both schemas in the (unfiltered) cache become Schema nodes with hierarchical ids."""
    nodes = transformer.transform_to_schema_nodes(extractor_with_cache.schema_info)
    by_name = {n.name: n for n in nodes}
    assert set(by_name) == {"public", "analytics"}
    assert by_name["public"].id == "neocarta_test.public"
    assert by_name["analytics"].id == "neocarta_test.analytics"


def test_transform_to_schema_nodes_filtered(transformer, extractor_with_cache):
    """A single-schema (filtered) cache yields exactly one Schema node."""
    schema_info = extractor_with_cache.schema_info
    only_public = schema_info[schema_info["schema_name"] == "public"]
    nodes = transformer.transform_to_schema_nodes(only_public)
    assert len(nodes) == 1
    assert nodes[0].name == "public"


def test_transform_to_table_nodes(transformer, extractor_with_cache):
    """Tables are transformed with database.schema.table ids."""
    nodes = transformer.transform_to_table_nodes(extractor_with_cache.table_info)
    by_name = {n.name: n for n in nodes}
    assert set(by_name) == {"customers", "orders", "daily_revenue"}
    assert by_name["orders"].id == "neocarta_test.public.orders"


def test_transform_to_column_nodes_maps_flags_and_type(transformer, extractor_with_cache):
    """Column nodes carry type, nullable, and primary/foreign-key flags."""
    nodes = transformer.transform_to_column_nodes(extractor_with_cache.column_info)
    by_id = {n.id: n for n in nodes}

    cust_id = by_id["neocarta_test.public.customers.id"]
    assert cust_id.type == "int4"
    assert cust_id.is_primary_key
    assert not cust_id.is_foreign_key
    assert not cust_id.nullable

    email = by_id["neocarta_test.public.customers.email"]
    assert email.nullable
    assert not email.is_primary_key

    fk = by_id["neocarta_test.public.orders.customer_id"]
    assert fk.is_foreign_key
    assert not fk.is_primary_key


def test_transform_to_has_schema_relationships(transformer, extractor_with_cache):
    """HAS_SCHEMA relationships link the database to each schema."""
    rels = transformer.transform_to_has_schema_relationships(extractor_with_cache.schema_info)
    assert len(rels) == 2
    assert all(r.database_id == "neocarta_test" for r in rels)
    assert {r.schema_id for r in rels} == {
        "neocarta_test.public",
        "neocarta_test.analytics",
    }


def test_transform_to_has_table_and_column_relationships(transformer, extractor_with_cache):
    """HAS_TABLE and HAS_COLUMN relationships are produced for every table/column."""
    has_table = transformer.transform_to_has_table_relationships(extractor_with_cache.table_info)
    assert len(has_table) == 3

    has_column = transformer.transform_to_has_column_relationships(extractor_with_cache.column_info)
    assert len(has_column) == 7


def test_transform_to_references_relationships(transformer, extractor_with_cache):
    """The single foreign key becomes a Column REFERENCES Column edge."""
    rels = transformer.transform_to_references_relationships(
        extractor_with_cache.column_references_info
    )
    assert len(rels) == 1
    assert rels[0].source_column_id == "neocarta_test.public.orders.customer_id"
    assert rels[0].target_column_id == "neocarta_test.public.customers.id"


def test_references_relationships_empty_when_no_foreign_keys(transformer, extractor):
    """An empty references cache yields no relationships (no errors)."""
    # extractor's cache is unpopulated → column_references_info is an empty frame.
    rels = transformer.transform_to_references_relationships(extractor.column_references_info)
    assert rels == []
