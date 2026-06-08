"""Extract OSI YAML content from a local file or URL."""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml


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
            response = httpx.get(source, timeout=self.http_timeout, follow_redirects=True)
            response.raise_for_status()
            return response.text

        return Path(source).read_text(encoding="utf-8")
