"""Unit tests for OsiConnector's OSI spec-version compatibility warnings."""

import warnings
from unittest.mock import MagicMock

import pytest

from neocarta.connectors.osi import OsiConnector, UnsupportedOsiVersionWarning


def _make_connector() -> OsiConnector:
    """Construct an OsiConnector with a mocked Neo4j driver."""
    return OsiConnector(neo4j_driver=MagicMock(), database_name="neo4j")


def test_supported_versions_advertised_on_class():
    """SUPPORTED_VERSIONS is a public class attribute discoverable from the class."""
    assert "0.1.1" in OsiConnector.SUPPORTED_VERSIONS


def test_unsupported_version_warning_is_a_user_warning_subclass():
    """The custom warning class subclasses UserWarning so existing filters still see it."""
    assert issubclass(UnsupportedOsiVersionWarning, UserWarning)


def test_unsupported_version_arg_warns_at_ingest_time():
    """Calling ingest with a version outside SUPPORTED_VERSIONS warns."""
    connector = _make_connector()
    # Patch out the IO-heavy stages so we can isolate the version-warning behavior.
    connector._load_ingest = MagicMock()  # type: ignore[method-assign]
    connector.loader.upsert_neocarta_graph_node = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(model_dump=MagicMock(return_value={}))
    )

    with (
        pytest.warns(UnsupportedOsiVersionWarning, match="outside the supported set"),
        _patch_extractor({"version": "9.9.9", "semantic_model": []}),
    ):
        connector.ingest("dummy_path.yaml", version="9.9.9")


def test_ingest_warns_when_spec_version_mismatches_provided_version():
    """A spec whose version doesn't match the ingest version arg warns."""
    connector = _make_connector()

    with pytest.warns(UnsupportedOsiVersionWarning, match=r"0\.2\.0.+0\.1\.1"):
        connector._check_spec_version(
            {"version": "0.2.0", "semantic_model": []},
            expected_version="0.1.1",
        )


def test_ingest_warns_when_spec_version_is_missing():
    """A spec with no top-level ``version`` field warns about unverifiable compatibility."""
    connector = _make_connector()

    with pytest.warns(UnsupportedOsiVersionWarning, match="no top-level `version` field"):
        connector._check_spec_version({"semantic_model": []}, expected_version="0.1.1")


def test_ingest_silent_when_spec_version_matches():
    """A spec whose version matches the expected version is silent."""
    connector = _make_connector()

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        connector._check_spec_version(
            {"version": "0.1.1", "semantic_model": []},
            expected_version="0.1.1",
        )

    assert [w for w in record if issubclass(w.category, UnsupportedOsiVersionWarning)] == []


def _patch_extractor(spec: dict):
    """Patch OsiSpecExtractor used in connector.ingest to return ``spec`` without IO."""
    from unittest.mock import patch

    extractor = MagicMock()
    extractor.extract.return_value = spec
    return patch(
        "neocarta.connectors.osi.connector.OsiSpecExtractor", return_value=extractor
    )
