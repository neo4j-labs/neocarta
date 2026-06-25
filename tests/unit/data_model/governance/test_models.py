"""Unit tests for the governance-tag data model components."""

import numpy as np
import pytest
from pydantic import ValidationError

from neocarta.data_model.governance import (
    GovernanceTag,
    GovernanceTagKey,
    GovernanceTagValue,
    HasDefinition,
    HasValueOption,
    TaggedWithGovernanceTag,
)


def test_governance_tag_key_optional_fields_default_to_none():
    key = GovernanceTagKey(id="src.sensitivity", name="sensitivity")
    assert key.description is None
    assert key.embedding is None


def test_governance_tag_key_carries_description_and_embedding():
    key = GovernanceTagKey(
        id="src.sensitivity",
        name="sensitivity",
        description="How sensitive the data is",
        embedding=[0.1, 0.2, 0.3],
    )
    assert key.description == "How sensitive the data is"
    assert key.embedding == [0.1, 0.2, 0.3]


def test_governance_tag_value_description_optional():
    """Databricks/Snowflake values are bare; the description field defaults to None."""
    value = GovernanceTagValue(id="src.sensitivity.pii", name="pii")
    assert value.description is None


def test_governance_tag_value_carries_description_for_gcp_style_values():
    value = GovernanceTagValue(
        id="src.sensitivity.pii", name="pii", description="Personally identifiable information"
    )
    assert value.description == "Personally identifiable information"


def test_governance_tag_value_nan_description_coerced_to_none():
    """A NaN description (e.g. from a pandas row) is normalised to None, not written."""
    value = GovernanceTagValue(id="src.sensitivity.pii", name="pii", description=np.nan)
    assert value.description is None


def test_governance_tag_instance_carries_key_and_value():
    tag = GovernanceTag(
        id="proj.sales.orders.email.sensitivity.pii", key="sensitivity", value="pii"
    )
    assert tag.key == "sensitivity"
    assert tag.value == "pii"


@pytest.mark.parametrize("missing", [None, np.nan])
def test_governance_tag_nan_or_none_key_value_coerced_to_empty_str(missing):
    """key/value are fed from a (pandas) source row, so NaN/None coerce to "" — not a crash."""
    tag = GovernanceTag(id="x", key=missing, value=missing)
    assert tag.key == ""
    assert tag.value == ""


def test_has_value_option_links_key_to_value():
    rel = HasValueOption(
        governance_tag_key_id="src.sensitivity",
        governance_tag_value_id="src.sensitivity.pii",
    )
    assert rel.governance_tag_key_id == "src.sensitivity"
    assert rel.governance_tag_value_id == "src.sensitivity.pii"


def test_has_definition_links_instance_to_value():
    rel = HasDefinition(
        governance_tag_id="proj.sales.orders.email.sensitivity.pii",
        governance_tag_value_id="src.sensitivity.pii",
    )
    assert rel.governance_tag_value_id == "src.sensitivity.pii"


@pytest.mark.parametrize("label", ["Column", "Table", "Schema"])
def test_tagged_with_governance_tag_accepts_taggable_labels(label):
    rel = TaggedWithGovernanceTag(
        source_label=label,
        source_id="some.source.id",
        governance_tag_id="some.source.id.sensitivity.pii",
    )
    assert rel.source_label == label


@pytest.mark.parametrize("label", ["BusinessTerm", "Metric", "Database", "GovernanceTag"])
def test_tagged_with_governance_tag_rejects_non_taggable_labels(label):
    """Only Column/Table/Schema can carry governance tags (matches the loaders)."""
    with pytest.raises(ValidationError):
        TaggedWithGovernanceTag(
            source_label=label,
            source_id="x",
            governance_tag_id="x.sensitivity.pii",
        )
