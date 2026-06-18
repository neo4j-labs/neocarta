"""Unit tests for DatabricksGlossaryExtractor (caching, filtering, error mapping)."""

from types import SimpleNamespace

import pytest

from neocarta.connectors.databricks.glossary.extract import DatabricksGlossaryExtractor
from neocarta.errors import AuthError, ConnectorError
from neocarta.warnings import DatabricksGlossaryWarning

from .conftest import METASTORE_ID


def test_cache_has_one_row_per_value_plus_value_less_tag(extractor_with_cache):
    df = extractor_with_cache._tag_policy_info
    # department(3) + cost_center(2) + free_form(1 null value) = 6; system tag excluded.
    assert len(df) == 6
    assert "system.certification_status" not in set(df["tag_key"])


def test_category_info_one_row_per_tag(extractor_with_cache):
    df = extractor_with_cache.category_info
    assert set(df["tag_key"]) == {"department", "cost_center", "free_form"}
    assert set(df["glossary_id"]) == {METASTORE_ID}
    department = df[df["tag_key"] == "department"].iloc[0]
    assert department["tag_description"] == "Owning department"
    assert department["tag_policy_id"] == "tp-department"


def test_business_term_info_excludes_value_less_tag(extractor_with_cache):
    df = extractor_with_cache.business_term_info
    assert set(df["value_name"]) == {"finance", "hr", "sales", "alpha", "beta"}
    # the value-less governed tag contributes no business term
    assert "free_form" not in set(df["tag_key"])


def test_glossary_info_uses_metastore_id(extractor_with_cache):
    df = extractor_with_cache.glossary_info
    assert len(df) == 1
    assert df.iloc[0]["glossary_id"] == METASTORE_ID
    assert df.iloc[0]["glossary_resource_path"] == METASTORE_ID


def test_include_system_tags_pulls_system_tag(extractor):
    extractor.extract(include_system_tags=True)
    assert "system.certification_status" in set(extractor.category_info["tag_key"])
    assert {"certified", "deprecated"} <= set(extractor.business_term_info["value_name"])


def test_empty_projections_before_extract(extractor):
    assert extractor.glossary_info.empty
    assert extractor.category_info.empty
    assert extractor.business_term_info.empty


def test_explicit_glossary_id_override(mock_workspace_client):
    extractor = DatabricksGlossaryExtractor(mock_workspace_client, glossary_id="my_tags")
    extractor.extract()
    assert extractor.glossary_info.iloc[0]["glossary_id"] == "my_tags"
    # the metastore is not consulted when an explicit id is given
    mock_workspace_client.metastores.summary.assert_not_called()


def test_host_fallback_warns_when_metastore_unavailable(mock_workspace_client):
    mock_workspace_client.metastores.summary.side_effect = RuntimeError("no metastore")
    mock_workspace_client.config = SimpleNamespace(host="https://dbc-test.example.com")
    extractor = DatabricksGlossaryExtractor(mock_workspace_client)
    with pytest.warns(DatabricksGlossaryWarning):
        extractor.extract()
    assert extractor.glossary_info.iloc[0]["glossary_id"] == "https://dbc-test.example.com"


def test_auth_failure_maps_to_auth_error(mock_workspace_client):
    from databricks.sdk.errors import Unauthenticated

    mock_workspace_client.tag_policies.list_tag_policies.side_effect = Unauthenticated("nope")
    extractor = DatabricksGlossaryExtractor(mock_workspace_client)
    with pytest.raises(AuthError):
        extractor.extract()


def test_generic_failure_maps_to_connector_error(mock_workspace_client):
    mock_workspace_client.tag_policies.list_tag_policies.side_effect = RuntimeError("boom")
    extractor = DatabricksGlossaryExtractor(mock_workspace_client)
    with pytest.raises(ConnectorError):
        extractor.extract()


def test_extract_against_genuine_sdk_objects(mock_workspace_client):
    """Read real databricks-sdk TagPolicy objects (built from API JSON), not look-alikes.

    Deserializing through the SDK's own ``TagPolicy.from_dict`` guarantees the
    extractor's attribute access (``tag_key`` / ``id`` / ``description`` /
    ``values[].name``) matches the genuine dataclasses, and that a value-less tag
    arrives as ``values == []``.
    """
    from databricks.sdk.service.tags import TagPolicy

    mock_workspace_client.tag_policies.list_tag_policies.return_value = [
        TagPolicy.from_dict(
            {
                "tag_key": "department",
                "id": "tp-department",
                "description": "Owning department",
                "values": [{"name": "finance"}, {"name": "hr"}],
            }
        ),
        TagPolicy.from_dict({"tag_key": "free_form", "id": "tp-free-form", "description": "x"}),
    ]
    extractor = DatabricksGlossaryExtractor(mock_workspace_client)
    extractor.extract()

    assert set(extractor.category_info["tag_key"]) == {"department", "free_form"}
    assert set(extractor.business_term_info["value_name"]) == {"finance", "hr"}
    department = extractor.category_info[extractor.category_info["tag_key"] == "department"].iloc[0]
    assert department["tag_description"] == "Owning department"
    assert department["tag_policy_id"] == "tp-department"
