import hashlib

from neocarta.connectors.utils.generate_id import (
    generate_governance_tag_instance_id,
    generate_governance_tag_key_id,
    generate_governance_tag_value_id,
    generate_node_id,
    generate_property_id,
    generate_relationship_id,
    generate_value_id,
)


def _h(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()[:32]


def test_governance_tag_key_id_namespaced_and_normalized():
    assert generate_governance_tag_key_id("aws:us-west-2:abc-123", "Cost Center") == (
        "aws:us_west_2:abc_123.cost_center"
    )


def test_governance_tag_value_id_namespaces_key_and_hashes_value():
    # source/key are normalized; the value segment is md5-hashed (not normalized).
    assert generate_governance_tag_value_id("acct", "sensitivity", "PII") == (
        f"acct.sensitivity.{_h('PII')}"
    )


def test_governance_tag_value_id_keeps_case_separator_variants_distinct():
    """Hashing the value prevents the silent collapse normalization would cause."""
    ids = {
        generate_governance_tag_value_id("acct", "risk", v)
        for v in ("High Risk", "high-risk", "high_risk")
    }
    assert len(ids) == 3
    # case-only variants are distinct too
    assert generate_governance_tag_value_id("acct", "s", "PII") != (
        generate_governance_tag_value_id("acct", "s", "pii")
    )


def test_governance_tag_instance_id_hashes_value_and_keeps_source_id_verbatim():
    # source_id is a pre-built (already-normalized) object id and is NOT re-normalized;
    # the value is hashed, mirroring generate_governance_tag_value_id.
    assert generate_governance_tag_instance_id("proj.sales.orders.email", "sensitivity", "PII") == (
        f"proj.sales.orders.email.sensitivity.{_h('PII')}"
    )


def test_governance_key_id_normalization_collapses_case_separator_variants():
    """Documented limitation: case/separator-variant KEYS still share one id (see README)."""
    base = generate_governance_tag_key_id("acct", "cost_center")
    assert generate_governance_tag_key_id("acct", "Cost Center") == base
    assert generate_governance_tag_key_id("acct", "cost-center") == base


def test_generate_value_id_string():
    """Test generating a value ID for a string value."""
    value_id = generate_value_id("my-project", "sales", "orders", "status", "completed")
    assert value_id


def test_generate_value_id_int():
    """Test generating a value ID for an int value."""
    value_id = generate_value_id("my-project", "sales", "orders", "status", 1)
    assert value_id


def test_generate_value_id_float():
    """Test generating a value ID for a float value."""
    value_id = generate_value_id("my-project", "sales", "orders", "status", 1.0)
    assert value_id


def test_generate_node_id_normalizes():
    assert generate_node_id("My-DBMS", "neo4j", "Person") == "my_dbms.neo4j.person"


def test_generate_relationship_id_normalizes():
    assert generate_relationship_id("My-DBMS", "neo4j", "KNOWS") == "my_dbms.neo4j.knows"


def test_generate_property_id_is_owner_scoped_and_not_double_normalized():
    node_id = generate_node_id("dbms", "neo4j", "Person")  # "dbms.neo4j.person"
    assert generate_property_id(node_id, "firstName") == "dbms.neo4j.person.firstname"


def test_property_id_distinct_across_owners_for_same_name():
    node_id = generate_node_id("dbms", "neo4j", "Person")
    rel_id = generate_relationship_id("dbms", "neo4j", "KNOWS")
    assert generate_property_id(node_id, "since") != generate_property_id(rel_id, "since")
