"""Unit tests for CollibraSchemaExtractor: scoping, attributes, parent resolution, warnings."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.collibra.schema.extract import CollibraSchemaExtractor
from neocarta.enums import NodeLabel
from neocarta.warnings import UnmappedCollibraAssetTypeWarning


def test_extract_populates_community_schema_table_column_caches(fake_client):
    """A full extract caches communities, schema domains, tables, and columns."""
    extractor = CollibraSchemaExtractor(fake_client)
    with pytest.warns(UnmappedCollibraAssetTypeWarning):
        extractor.extract()
    assert list(extractor.community_info["community_id"]) == ["comm-sales"]
    assert list(extractor.schema_domain_info["domain_id"]) == ["dom-wh"]
    assert set(extractor.table_info["asset_id"]) == {"a-orders"}
    assert set(extractor.column_info["asset_id"]) == {"a-orderid", "a-custid"}


def test_only_schema_domains_are_kept(fake_client):
    """The glossary domain is excluded from the schema extractor's domains."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract()
    assert "dom-gloss" not in set(extractor.schema_domain_info["domain_id"])


def test_descriptions_are_attached_from_attributes(fake_client):
    """Description/Definition attribute values populate each asset's description."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract()
    orders = extractor.table_info.set_index("asset_id").loc["a-orders"]
    order_id = extractor.column_info.set_index("asset_id").loc["a-orderid"]
    assert orders["description"] == "All sales orders"
    assert order_id["description"] == "Order identifier"


def test_columns_resolve_parent_table(fake_client):
    """Each column row records its parent table UUID from contains-column relations."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract()
    parents = extractor.column_info.set_index("asset_id")["table_collibra_id"].to_dict()
    assert parents == {"a-orderid": "a-orders", "a-custid": "a-orders"}


def test_attributes_fetched_with_single_assetid_param(fake_client):
    """Attributes are fetched per asset via a single ``assetId`` (not an array param)."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract()
    attr_calls = [
        c.args[1]
        for c in fake_client.get_paginated.call_args_list
        if c.args[0] == "/rest/2.0/attributes"
    ]
    assert attr_calls, "no attribute requests were made"
    for params in attr_calls:
        assert isinstance(params.get("assetId"), str)
        assert "assetId[]" not in params


def test_unmapped_asset_types_emit_warning(fake_client):
    """Out-of-scope asset types (e.g. Data Quality Rule) are skipped with a warning."""
    extractor = CollibraSchemaExtractor(fake_client)
    with pytest.warns(UnmappedCollibraAssetTypeWarning, match="Data Quality Rule"):
        extractor.extract()


def test_include_nodes_columns_only_still_caches_tables_transiently(fake_client):
    """With include_nodes=[COLUMN], tables are cached transiently for parent resolution."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract(include_nodes=[NodeLabel.COLUMN])
    assert not extractor.column_info.empty
    assert not extractor.table_info.empty  # kept to resolve column parents


def test_asset_type_names_scopes_via_type_uuid(fake_client):
    """asset_type_names resolves to type UUIDs passed to the assets endpoint."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract(asset_type_names=["Table"])
    asset_calls = [
        c.args[1]
        for c in fake_client.get_paginated.call_args_list
        if c.args[0] == "/rest/2.0/assets"
    ]
    assert asset_calls
    assert all(params.get("typeId") == ["at-table"] for params in asset_calls)
    # Only the table asset survives the type filter.
    assert set(extractor.table_info["asset_id"]) == {"a-orders"}
    assert extractor.column_info.empty


def test_extract_replaces_previous_cache(fake_client):
    """Each extract() replaces prior cache state (no accumulation)."""
    extractor = CollibraSchemaExtractor(fake_client)
    extractor.extract()
    first = len(extractor.table_info)
    extractor.extract()
    assert len(extractor.table_info) == first


def test_extract_with_empty_instance_yields_empty_caches():
    """An instance with no communities/domains yields empty (not erroring) caches."""
    client = MagicMock()
    client.discover_types.return_value = ({}, {}, {})
    client.get_paginated.side_effect = lambda *_args, **_kwargs: []
    extractor = CollibraSchemaExtractor(client)
    extractor.extract()
    assert extractor.community_info.empty
    assert extractor.table_info.empty
