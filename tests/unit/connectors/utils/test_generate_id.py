from neocarta.connectors.utils.generate_id import (
    generate_governance_tag_instance_id,
    generate_governance_tag_key_id,
    generate_governance_tag_value_id,
    generate_value_id,
)


def test_governance_tag_key_id_namespaced_and_normalized():
    assert generate_governance_tag_key_id("aws:us-west-2:abc-123", "Cost Center") == (
        "aws:us_west_2:abc_123.cost_center"
    )


def test_governance_tag_value_id_namespaced_and_normalized():
    assert generate_governance_tag_value_id("acct", "sensitivity", "PII") == "acct.sensitivity.pii"


def test_governance_tag_instance_id_is_per_assignment_and_keeps_source_id_verbatim():
    # source_id is a pre-built (already-normalized) object id and is NOT re-normalized.
    assert generate_governance_tag_instance_id("proj.sales.orders.email", "sensitivity", "PII") == (
        "proj.sales.orders.email.sensitivity.pii"
    )


def test_governance_key_id_normalization_collapses_case_separator_variants():
    """Documented limitation: case/separator-variant keys share one id (see README)."""
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
