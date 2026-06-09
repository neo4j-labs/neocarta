"""Unit tests for CollibraTypeResolver: type classification and UUID resolution."""

from neocarta.connectors.collibra.resolve import CollibraTypeResolver

from .conftest import ASSET_TYPES, DOMAIN_TYPES, RELATION_TYPES


def _resolver() -> CollibraTypeResolver:
    return CollibraTypeResolver(ASSET_TYPES, DOMAIN_TYPES, RELATION_TYPES)


def test_neocarta_asset_type_maps_known_and_returns_none_for_unmapped():
    """Asset type names map to neocarta node types; unmapped types return None."""
    r = _resolver()
    assert r.neocarta_asset_type("Table") == "Table"
    assert r.neocarta_asset_type("column") == "Column"  # case-insensitive
    assert r.neocarta_asset_type("Data Category") == "Category"
    assert r.neocarta_asset_type("Business Term") == "BusinessTerm"
    assert r.neocarta_asset_type("Data Quality Rule") is None


def test_neocarta_domain_type_defaults_to_schema():
    """Domain types classify into Schema/Glossary, defaulting to Schema."""
    r = _resolver()
    assert r.neocarta_domain_type("Physical Data Dictionary") == "Schema"
    assert r.neocarta_domain_type("Business Glossary") == "Glossary"
    assert r.neocarta_domain_type("Some Custom Domain Type") == "Schema"


def test_neocarta_relation_maps_known():
    """Relation type names map to neocarta relationship types."""
    r = _resolver()
    assert r.neocarta_relation("Table contains Column") == "HAS_COLUMN"
    assert r.neocarta_relation("Category / Business Term") == "HAS_BUSINESS_TERM"
    assert r.neocarta_relation("Asset associated with Business Term") == "TAGGED_WITH"
    assert r.neocarta_relation("Unknown Relation") is None


def test_asset_type_ids_for_names_resolves_uuids_case_insensitively():
    """Display names resolve to their type UUIDs; unknown names are dropped."""
    r = _resolver()
    assert sorted(r.asset_type_ids_for_names(["Table", "column"])) == ["at-col", "at-table"]
    assert r.asset_type_ids_for_names(["Nonexistent"]) == []


def test_relation_type_ids_for_neocarta():
    """Resolve the relation-type UUIDs whose alias maps into the requested set."""
    r = _resolver()
    assert r.relation_type_ids_for_neocarta({"HAS_COLUMN"}) == ["rt-contains"]
    assert set(r.relation_type_ids_for_neocarta({"HAS_BUSINESS_TERM", "TAGGED_WITH"})) == {
        "rt-cat-term",
        "rt-tag",
    }
