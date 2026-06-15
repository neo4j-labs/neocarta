"""Transform a graph snapshot back into an OSI YAML document."""

import json
from pathlib import Path
from typing import Any

import yaml


class _InlineList(list):
    """List subclass that PyYAML renders in flow style (``[a, b]``).

    Used for simple string-list fields like ``primary_key``, ``from_columns``,
    ``to_columns``, and each inner list of ``unique_keys`` — matches the
    formatting used in upstream OSI sample files and keeps the YAML compact.
    """

    __slots__ = ()


class _LiteralBlock(str):
    """String subclass that PyYAML renders as a literal block scalar (``|``).

    Used for the ``data`` field of OsiCustomExtensions so JSON payloads land in
    the YAML output as indented multi-line literals rather than a single
    quoted string.
    """

    __slots__ = ()


def _represent_inline_list(dumper: yaml.SafeDumper, data: _InlineList) -> Any:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def _represent_literal_block(dumper: yaml.SafeDumper, data: _LiteralBlock) -> Any:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.SafeDumper.add_representer(_InlineList, _represent_inline_list)
yaml.SafeDumper.add_representer(_LiteralBlock, _represent_literal_block)


class OsiExportTransformer:
    """
    Serialize a graph snapshot (from :class:`OsiGraphExtractor`) into the OSI YAML
    format.

    The transformer owns the dict produced by :meth:`transform` and writes the
    rendered YAML via :meth:`to_yaml`.
    """

    def __init__(self) -> None:
        """Initialize the transformer with an empty cached spec."""
        self.spec: dict[str, Any] | None = None

    def transform(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Build an OSI spec dict from a graph snapshot.

        Parameters
        ----------
        snapshot : dict[str, Any]
            The structured graph snapshot produced by
            :class:`OsiGraphExtractor.extract`.

        Returns:
        -------
        dict[str, Any]
            The OSI spec as a Python dict (YAML-serializable). Cached as
            :attr:`spec`.
        """
        model: dict[str, Any] = {"name": snapshot["name"]}
        self._maybe_set(model, "description", snapshot.get("description"))
        self._set_ai_context(model, snapshot.get("ai_context"))

        model["datasets"] = [self._dataset_to_yaml(ds) for ds in snapshot.get("datasets", [])]

        relationships = [
            self._relationship_to_yaml(rel) for rel in snapshot.get("relationships", [])
        ]
        if relationships:
            model["relationships"] = relationships

        metrics = [self._metric_to_yaml(m) for m in snapshot.get("metrics", [])]
        if metrics:
            model["metrics"] = metrics

        customs = self._customs_to_yaml(snapshot.get("custom_extensions"))
        if customs:
            model["custom_extensions"] = customs

        spec: dict[str, Any] = {"semantic_model": [model]}
        version = snapshot.get("osi_version")
        if version:
            spec = {"version": version, **spec}

        self.spec = spec
        return spec

    def _to_yaml(self, output_path: str | Path) -> None:
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

    # ------------------------------------------------------------------ #
    # Per-entity reshaping
    # ------------------------------------------------------------------ #

    def _dataset_to_yaml(self, dataset: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"name": dataset["name"]}
        self._maybe_set(out, "source", dataset.get("source"))

        primary_key = dataset.get("primary_key")
        if primary_key:
            out["primary_key"] = _InlineList(primary_key)

        unique_keys = dataset.get("unique_keys")
        if unique_keys:
            out["unique_keys"] = [_InlineList(uk) for uk in unique_keys]

        self._maybe_set(out, "description", dataset.get("description"))
        self._set_ai_context(out, dataset.get("ai_context"))

        fields = [self._field_to_yaml(f) for f in dataset.get("fields", [])]
        if fields:
            out["fields"] = fields

        customs = self._customs_to_yaml(dataset.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _field_to_yaml(self, field: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"name": field["name"]}

        expressions = field.get("expressions") or []
        if expressions:
            out["expression"] = {
                "dialects": [
                    {"dialect": e["dialect"], "expression": e["expression"]} for e in expressions
                ]
            }

        # ``is_time_dimension`` is tri-state: None means the OSI input had no
        # ``dimension`` key (omit on export), True/False are explicit declarations.
        is_time_dim = field.get("is_time_dimension")
        if is_time_dim is not None:
            out["dimension"] = {"is_time": is_time_dim}

        self._maybe_set(out, "label", field.get("label"))
        self._maybe_set(out, "description", field.get("description"))
        self._set_ai_context(out, field.get("ai_context"))

        customs = self._customs_to_yaml(field.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _relationship_to_yaml(self, relationship: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": relationship["name"],
            "from": relationship["from"],
            "to": relationship["to"],
            "from_columns": _InlineList(relationship.get("from_columns") or []),
            "to_columns": _InlineList(relationship.get("to_columns") or []),
        }
        customs = self._customs_to_yaml(relationship.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _metric_to_yaml(self, metric: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"name": metric["name"]}

        expressions = metric.get("expressions") or []
        if expressions:
            out["expression"] = {
                "dialects": [
                    {"dialect": e["dialect"], "expression": e["expression"]} for e in expressions
                ]
            }

        self._maybe_set(out, "description", metric.get("description"))
        self._set_ai_context(out, metric.get("ai_context"))

        customs = self._customs_to_yaml(metric.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _customs_to_yaml(self, customs: Any) -> list[dict[str, Any]]:
        """
        Reshape a list of {vendor_name, data} aspect dicts into OSI YAML form.

        Pretty-prints JSON payloads in ``data`` and tags them with
        :class:`_LiteralBlock` so the YAML renders them as a ``|`` block scalar
        rather than a single quoted string.
        """
        if not customs:
            return []
        return [
            {
                "vendor_name": c.get("vendor_name") or "",
                "data": self._format_extension_data(c.get("data")),
            }
            for c in customs
            if c is not None
        ]

    @staticmethod
    def _parse_stored_ai_context(value: Any) -> Any:
        """
        Convert a stored ``ai_context`` payload back to its native YAML structure.

        Ingest JSON-encodes dict-typed ai_context before writing to the graph;
        on export we parse it back so the YAML reflects the original nested
        shape (``synonyms:`` as a list, etc.) rather than a quoted JSON blob.
        Non-JSON strings pass through unchanged.
        """
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return value

    @staticmethod
    def _format_extension_data(data: Any) -> Any:
        """
        Pretty-print a custom-extension ``data`` JSON payload and return it as a
        :class:`_LiteralBlock` so the YAML renders it as a multi-line ``|`` block.
        Non-JSON strings pass through unchanged.
        """
        if not isinstance(data, str) or not data:
            return data
        try:
            parsed = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            return data
        # Trailing newline forces PyYAML to emit ``|`` (clip) rather than
        # ``|-`` (strip), matching the upstream OSI sample formatting.
        return _LiteralBlock(json.dumps(parsed, indent=2) + "\n")

    @classmethod
    def _set_ai_context(cls, target: dict[str, Any], value: Any) -> None:
        """Parse ``value`` (stored JSON string or already-native) and set it if non-empty."""
        parsed = cls._parse_stored_ai_context(value)
        if parsed in (None, "", [], {}):
            return
        target["ai_context"] = parsed

    @staticmethod
    def _maybe_set(target: dict[str, Any], key: str, value: Any) -> None:
        """Set ``target[key] = value`` only when ``value`` is non-empty / non-None."""
        if value in (None, "", [], {}):
            return
        target[key] = value
