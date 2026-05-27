"""Transform a graph snapshot back into an OSI YAML document."""

from pathlib import Path
from typing import Any

import yaml


class OsiExportTransformer:
    """
    Serialize a graph snapshot (from :class:`OsiGraphExtractor`) into the OSI YAML format.

    The transformer owns the dict produced by :meth:`transform` and the rendered YAML
    produced by :meth:`to_yaml`.
    """

    def __init__(self) -> None:
        self.spec: dict[str, Any] | None = None

    def transform(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Build an OSI spec dict from a graph snapshot.

        Parameters
        ----------
        snapshot : dict[str, Any]
            The structured graph snapshot produced by :class:`OsiGraphExtractor`.

        Returns:
        -------
        dict[str, Any]
            The OSI spec as a Python dict (YAML-serializable). Cached as ``self.spec``.
        """
        raise NotImplementedError("OsiExportTransformer.transform is not yet implemented")

    def to_yaml(self, output_path: str | Path) -> None:
        """
        Write the cached OSI spec dict to ``output_path`` as YAML.

        Must be called after :meth:`transform`.
        """
        if self.spec is None:
            raise RuntimeError("OsiExportTransformer.transform must be called before to_yaml")
        Path(output_path).write_text(
            yaml.safe_dump(self.spec, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
