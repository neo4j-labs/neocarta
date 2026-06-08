"""Unit tests for the OSI ingest extractor (YAML loading from path or URL)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.osi.ingest.extract import OsiSpecExtractor


def test_extract_from_path_object(tpcds_yaml_path: Path):
    """A pathlib.Path source loads and parses to a dict with semantic_model."""
    extractor = OsiSpecExtractor()
    spec = extractor.extract(tpcds_yaml_path)

    assert isinstance(spec, dict)
    assert "semantic_model" in spec
    assert spec["semantic_model"][0]["name"] == "tpcds_retail_model"
    assert spec["version"] == "0.2.0.dev0"


def test_extract_from_string_path(tpcds_yaml_path: Path):
    """A string filesystem path (no http scheme) loads from disk."""
    extractor = OsiSpecExtractor()
    spec = extractor.extract(str(tpcds_yaml_path))

    assert spec["semantic_model"][0]["name"] == "tpcds_retail_model"


def test_extract_caches_result_on_instance(tpcds_yaml_path: Path):
    """extract() caches the parsed spec on the instance as ``spec``."""
    extractor = OsiSpecExtractor()
    assert extractor.spec is None

    spec = extractor.extract(tpcds_yaml_path)
    assert extractor.spec is spec


def test_extract_from_https_url_uses_httpx():
    """URL sources go through httpx.get and parse the response text as YAML."""
    yaml_body = """
version: "0.2.0"
semantic_model:
  - name: url_model
    datasets: []
""".strip()
    mock_response = MagicMock()
    mock_response.text = yaml_body
    mock_response.raise_for_status = MagicMock()

    with patch(
        "neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response
    ) as mock_get:
        extractor = OsiSpecExtractor(http_timeout=5.0)
        spec = extractor.extract("https://example.com/spec.yaml")

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://example.com/spec.yaml"
    assert kwargs.get("timeout") == 5.0
    assert spec["semantic_model"][0]["name"] == "url_model"


def test_extract_http_url_also_routed_to_httpx():
    """``http://`` sources are also routed through httpx (not treated as a file)."""
    mock_response = MagicMock()
    mock_response.text = "version: '0.2.0'\nsemantic_model: []\n"
    mock_response.raise_for_status = MagicMock()

    with patch("neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response):
        spec = OsiSpecExtractor().extract("http://example.com/spec.yaml")

    assert spec["semantic_model"] == []


def test_extract_non_mapping_yaml_raises(tmp_path: Path):
    """YAML that parses to a non-dict (e.g. a list) raises TypeError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(TypeError, match="did not parse to a mapping"):
        OsiSpecExtractor().extract(bad)


def test_extract_missing_file_raises(tmp_path: Path):
    """Missing local file raises FileNotFoundError from the underlying read."""
    with pytest.raises(FileNotFoundError):
        OsiSpecExtractor().extract(tmp_path / "does_not_exist.yaml")


def test_extract_empty_yaml_raises(tmp_path: Path):
    """An empty YAML file parses to None, which is not a mapping — TypeError."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(TypeError, match="did not parse to a mapping"):
        OsiSpecExtractor().extract(empty)


def test_extract_url_http_error_propagates():
    """4xx/5xx responses surface via response.raise_for_status()."""
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
    )

    with patch("neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response):
        with pytest.raises(httpx.HTTPStatusError):
            OsiSpecExtractor().extract("https://example.com/missing.yaml")
