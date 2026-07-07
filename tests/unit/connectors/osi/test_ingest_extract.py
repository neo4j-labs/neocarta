"""Unit tests for the OSI ingest extractor (YAML loading from path or URL)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.osi.ingest.extract import OsiSpecExtractor, _assert_public_url
from neocarta.errors import ConfigError

# A getaddrinfo() result for a public IPv4 address, used to let the SSRF guard's
# allow-path run in the URL happy-path tests without a real DNS lookup.
_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]
_PRIVATE_ADDRINFO = [(2, 1, 6, "", ("10.1.2.3", 0))]


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
    mock_response.is_redirect = False
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ),
        patch(
            "neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response
        ) as mock_get,
    ):
        extractor = OsiSpecExtractor(http_timeout=5.0)
        spec = extractor.extract("https://example.com/spec.yaml")

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://example.com/spec.yaml"
    assert kwargs.get("timeout") == 5.0
    # Redirects are not followed, to prevent an SSRF pivot from an allowed host.
    assert kwargs.get("follow_redirects") is False
    assert spec["semantic_model"][0]["name"] == "url_model"


def test_extract_http_url_also_routed_to_httpx():
    """``http://`` sources are also routed through httpx (not treated as a file)."""
    mock_response = MagicMock()
    mock_response.text = "version: '0.2.0'\nsemantic_model: []\n"
    mock_response.is_redirect = False
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ),
        patch("neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response),
    ):
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
    mock_response.is_redirect = False
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
    )

    with (
        patch(
            "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ),
        patch("neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response),
        pytest.raises(httpx.HTTPStatusError),
    ):
        OsiSpecExtractor().extract("https://example.com/missing.yaml")


# --- SSRF guard (V-02) ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://127.0.0.1/spec.yaml",  # loopback
        "http://10.0.0.5/spec.yaml",  # RFC-1918 private
        "http://[::1]/spec.yaml",  # IPv6 loopback
        "http://100.64.0.1/spec.yaml",  # CGNAT (not is_global; missed by is_private)
        "http://224.0.0.1/spec.yaml",  # multicast (is_global=True on some Pythons)
        "http://[::ffff:169.254.169.254]/x",  # IPv4-mapped IPv6 -> link-local
    ],
)
def test_url_resolving_to_non_public_address_is_rejected(url):
    """Literal internal addresses are refused before any request is made.

    Covers CGNAT, multicast, and IPv4-mapped IPv6 in addition to the obvious
    loopback/link-local/private ranges.
    """
    with patch("neocarta.connectors.osi.ingest.extract.httpx.get") as mock_get:
        with pytest.raises(ConfigError, match=r"non-public|SSRF"):
            OsiSpecExtractor().extract(url)
    mock_get.assert_not_called()


def test_hostname_resolving_to_private_ip_is_rejected():
    """A name that resolves (via DNS) to an internal IP is also blocked."""
    with (
        patch(
            "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
            return_value=_PRIVATE_ADDRINFO,
        ),
        patch("neocarta.connectors.osi.ingest.extract.httpx.get") as mock_get,
    ):
        with pytest.raises(ConfigError, match="non-public"):
            OsiSpecExtractor().extract("https://sneaky.internal.example/spec.yaml")
    mock_get.assert_not_called()


def test_url_without_host_is_rejected():
    """A URL with no host raises before any lookup or request."""
    with pytest.raises(ConfigError, match="no host"):
        _assert_public_url("http:///spec.yaml")


def test_unresolvable_host_is_rejected():
    """A host that cannot be resolved is refused with a clear error."""
    import socket

    with patch(
        "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
        side_effect=socket.gaierror("name resolution failed"),
    ):
        with pytest.raises(ConfigError, match="resolve"):
            _assert_public_url("https://does-not-exist.invalid/spec.yaml")


def test_redirect_response_is_rejected():
    """A redirect from an allowed host cannot pivot to an internal address."""
    mock_response = MagicMock()
    mock_response.is_redirect = True

    with (
        patch(
            "neocarta.connectors.osi.ingest.extract.socket.getaddrinfo",
            return_value=_PUBLIC_ADDRINFO,
        ),
        patch("neocarta.connectors.osi.ingest.extract.httpx.get", return_value=mock_response),
    ):
        with pytest.raises(ConfigError, match="redirect"):
            OsiSpecExtractor().extract("https://example.com/spec.yaml")
