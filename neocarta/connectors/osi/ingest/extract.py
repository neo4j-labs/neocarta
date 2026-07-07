"""Extract OSI YAML content from a local file or URL."""

import ipaddress
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from ...._logging import log_stage
from ....errors import ConfigError


def _assert_public_url(url: str) -> None:
    """Refuse to fetch a URL that resolves to a non-public address.

    Guards the URL-fetch path against server-side request forgery (SSRF): a
    ``spec_source`` that resolves to a loopback, link-local (incl. the cloud
    metadata endpoint ``169.254.169.254``), private, reserved, multicast, or
    unspecified address is rejected before any request is made. Every address the
    host resolves to is checked, so a name that maps to an internal IP cannot slip
    through.

    Parameters
    ----------
    url : str
        The ``http(s)`` URL about to be fetched.

    Raises:
    ------
    ConfigError
        If the URL has no host, cannot be resolved, or resolves to any
        non-public address.
    """
    host = urlparse(url).hostname
    if not host:
        raise ConfigError(
            f"OSI spec URL {url!r} has no host.",
            suggestion="Provide a valid http(s):// URL or a local file path.",
        )
    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ConfigError(
            f"Could not resolve host {host!r} for OSI spec URL {url!r}.",
            suggestion="Check the URL's host, or provide a local file path.",
        ) from exc

    for *_, sockaddr in addrinfo:
        # sockaddr[0] is the numeric address; IPv6 link-local may carry a %zone.
        ip = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) so the embedded
        # IPv4 is classified: is_private/is_global do not delegate to the mapped
        # address on Python 3.10/3.11, which would otherwise let it slip through.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        # Reject anything that is not globally routable — `not is_global` also
        # covers ranges the explicit list misses (CGNAT 100.64/10, TEST-NET) —
        # OR that falls in a non-global special range `is_global` misses (notably
        # multicast, which reports is_global=True on some Python versions).
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ConfigError(
                f"OSI spec URL {url!r} resolves to a non-public address ({ip}); "
                "refusing to fetch it to prevent SSRF.",
                suggestion="Point --spec-source at a public URL or a local file path.",
            )


class OsiSpecExtractor:
    """
    Load and parse an OSI YAML spec from a local file path or an HTTP(S) URL.

    Parameters
    ----------
    http_timeout : float, default 30.0
        Timeout in seconds for URL fetches.
    """

    def __init__(self, http_timeout: float = 30.0) -> None:
        """Initialize the extractor with an HTTP timeout."""
        self.http_timeout = http_timeout
        self.spec: dict[str, Any] | None = None

    @log_stage(count=False)
    def extract(self, spec_source: str | Path) -> dict[str, Any]:
        """
        Read the OSI spec from ``spec_source`` and parse it as YAML.

        Parameters
        ----------
        spec_source : str | Path
            A filesystem path or an ``http(s)://`` URL pointing to the OSI YAML.

        Returns:
        -------
        dict[str, Any]
            The parsed YAML document as a Python dict. Cached on the instance as
            ``self.spec``; replaces any prior cached value.
        """
        raw = self._read_raw(spec_source)
        parsed = yaml.safe_load(raw)
        if not isinstance(parsed, dict):
            raise TypeError(
                f"OSI spec at {spec_source!r} did not parse to a mapping; "
                f"got {type(parsed).__name__}"
            )
        self.spec = parsed
        return parsed

    def _read_raw(self, source: str | Path) -> str:
        """Read raw YAML text from a path or URL."""
        if isinstance(source, Path):
            return source.read_text(encoding="utf-8")

        scheme = urlparse(source).scheme.lower()
        if scheme in ("http", "https"):
            _assert_public_url(source)
            # follow_redirects=False: a redirect from an allowed host could
            # otherwise pivot to an internal address the initial check cleared.
            response = httpx.get(source, timeout=self.http_timeout, follow_redirects=False)
            if response.is_redirect:
                raise ConfigError(
                    f"OSI spec URL {source!r} returned a redirect; redirects are not "
                    "followed to prevent SSRF pivots.",
                    suggestion="Provide the final direct URL to the OSI YAML, or a local file path.",
                )
            response.raise_for_status()
            return response.text

        return Path(source).read_text(encoding="utf-8")
