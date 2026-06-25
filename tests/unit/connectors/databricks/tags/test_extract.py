"""Unit tests for DatabricksTagsExtractor (caching, filtering, error mapping)."""

from types import SimpleNamespace

import pytest

from neocarta.connectors.databricks.tags.extract import (
    DEFAULT_SYSTEM_PREFIXES,
    DatabricksTagsExtractor,
)
from neocarta.errors import AuthError, ConnectorError, StateError
from neocarta.warnings import DatabricksTagsWarning

from .conftest import METASTORE_ID, _tag_policy

# A user-authored tag plus one tag under each default platform prefix.
_MIXED_POLICIES = [
    _tag_policy("department", "Owning department", "tp-dep", ["finance"]),
    _tag_policy("system.certification_status", "sys", "tp-sys", ["certified"]),
    _tag_policy("class.pii", "classification", "tp-class", ["high"]),
    _tag_policy("ai.model_family", "ai", "tp-ai", ["gpt"]),
    _tag_policy("sap.PersonalData.isPotentiallyPersonal", "sap", "tp-sap", ["true"]),
]


def test_cache_has_one_row_per_value_plus_value_less_tag(extractor_with_cache):
    df = extractor_with_cache._tag_policy_info
    # department(3) + cost_center(2) + free_form(1 null value) = 6; system tag excluded.
    assert len(df) == 6
    assert "system.certification_status" not in set(df["tag_key"])


def test_tag_key_info_one_row_per_tag(extractor_with_cache):
    df = extractor_with_cache.tag_key_info
    assert set(df["tag_key"]) == {"department", "cost_center", "free_form"}
    assert set(df["source"]) == {METASTORE_ID}
    department = df[df["tag_key"] == "department"].iloc[0]
    assert department["tag_description"] == "Owning department"


def test_tag_value_info_excludes_value_less_tag(extractor_with_cache):
    df = extractor_with_cache.tag_value_info
    assert set(df["value_name"]) == {"finance", "hr", "sales", "alpha", "beta"}
    # the value-less governed tag contributes no value option
    assert "free_form" not in set(df["tag_key"])


def test_source_resolves_to_metastore_id(extractor_with_cache):
    assert extractor_with_cache.source == METASTORE_ID


def test_include_system_tags_pulls_system_tag(extractor):
    extractor.extract(include_system_tags=True)
    assert "system.certification_status" in set(extractor.tag_key_info["tag_key"])
    assert {"certified", "deprecated"} <= set(extractor.tag_value_info["value_name"])


def test_empty_projections_before_extract(extractor):
    assert extractor.tag_key_info.empty
    assert extractor.tag_value_info.empty
    assert extractor.source is None


def test_extract_tag_policies_before_resolve_raises_state_error(extractor):
    """Calling the stage directly (skipping extract()'s source resolution) fails fast
    rather than namespacing ids on None."""
    with pytest.raises(StateError):
        extractor.extract_tag_policies()


def test_explicit_source_override(mock_workspace_client):
    extractor = DatabricksTagsExtractor(mock_workspace_client, source="my_account")
    extractor.extract()
    assert extractor.source == "my_account"
    assert set(extractor.tag_key_info["source"]) == {"my_account"}
    # the metastore is not consulted when an explicit source is given
    mock_workspace_client.metastores.summary.assert_not_called()


def test_host_fallback_warns_when_metastore_unavailable(mock_workspace_client):
    mock_workspace_client.metastores.summary.side_effect = RuntimeError("no metastore")
    mock_workspace_client.config = SimpleNamespace(host="https://dbc-test.example.com")
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    with pytest.warns(DatabricksTagsWarning):
        extractor.extract()
    assert extractor.source == "https://dbc-test.example.com"


def test_auth_failure_maps_to_auth_error(mock_workspace_client):
    from databricks.sdk.errors import Unauthenticated

    mock_workspace_client.tag_policies.list_tag_policies.side_effect = Unauthenticated("nope")
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    with pytest.raises(AuthError):
        extractor.extract()


def test_generic_failure_maps_to_connector_error(mock_workspace_client):
    mock_workspace_client.tag_policies.list_tag_policies.side_effect = RuntimeError("boom")
    extractor = DatabricksTagsExtractor(mock_workspace_client)
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
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    extractor.extract()

    assert set(extractor.tag_key_info["tag_key"]) == {"department", "free_form"}
    assert set(extractor.tag_value_info["value_name"]) == {"finance", "hr"}
    department = extractor.tag_key_info[extractor.tag_key_info["tag_key"] == "department"].iloc[0]
    assert department["tag_description"] == "Owning department"


def test_default_prefixes_exclude_all_platform_namespaces(mock_workspace_client):
    """By default every system./class./ai./sap. tag is dropped; user tags survive."""
    assert DEFAULT_SYSTEM_PREFIXES == ("system.", "class.", "ai.", "sap.")
    mock_workspace_client.tag_policies.list_tag_policies.return_value = _MIXED_POLICIES
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    extractor.extract()
    assert set(extractor.tag_key_info["tag_key"]) == {"department"}


def test_custom_system_prefixes_only_excludes_given(mock_workspace_client):
    """Narrowing to ('system.',) keeps class./ai./sap. tags."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = _MIXED_POLICIES
    extractor = DatabricksTagsExtractor(mock_workspace_client, system_prefixes=("system.",))
    extractor.extract()
    assert set(extractor.tag_key_info["tag_key"]) == {
        "department",
        "class.pii",
        "ai.model_family",
        "sap.PersonalData.isPotentiallyPersonal",
    }


def test_include_system_tags_overrides_prefixes(mock_workspace_client):
    """include_system_tags=True ingests everything regardless of the prefix set."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = _MIXED_POLICIES
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    extractor.extract(include_system_tags=True)
    assert len(set(extractor.tag_key_info["tag_key"])) == 5


def test_empty_system_prefixes_disables_filtering(mock_workspace_client):
    """An empty prefix set means no prefix-based exclusion."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = _MIXED_POLICIES
    extractor = DatabricksTagsExtractor(mock_workspace_client, system_prefixes=())
    extractor.extract()
    assert len(set(extractor.tag_key_info["tag_key"])) == 5


def test_none_or_empty_tag_key_is_skipped_not_an_error(mock_workspace_client):
    """A malformed policy (no key) is skipped, not reported as a listing failure."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = [
        _tag_policy(None, "no key", "tp-none", ["x"]),
        _tag_policy("", "empty key", "tp-empty", ["y"]),
        _tag_policy("department", "ok", "tp-dep", ["finance"]),
    ]
    extractor = DatabricksTagsExtractor(mock_workspace_client)
    extractor.extract()  # must not raise
    assert set(extractor.tag_key_info["tag_key"]) == {"department"}
