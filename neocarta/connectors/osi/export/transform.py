"""Transform a graph snapshot back into an OSI YAML document."""

from pathlib import Path
from typing import Any

import yaml


class OsiExportTransformer:
    """
    Serialize a graph snapshot (from :class:`OsiGraphExtractor`) into the OSI YAML
    format.

    The transformer owns the dict produced by :meth:`transform` and writes the
    rendered YAML via :meth:`to_yaml`.
    """

    def __init__(self) -> None:
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
        self._maybe_set(model, "ai_context", snapshot.get("ai_context"))

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

    # ------------------------------------------------------------------ #
    # Per-entity reshaping
    # ------------------------------------------------------------------ #

    def _dataset_to_yaml(self, dataset: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"name": dataset["name"]}
        self._maybe_set(out, "source", dataset.get("source"))
        self._maybe_set(out, "primary_key", dataset.get("primary_key"))
        self._maybe_set(out, "unique_keys", dataset.get("unique_keys"))
        self._maybe_set(out, "description", dataset.get("description"))
        self._maybe_set(out, "ai_context", dataset.get("ai_context"))

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
                    {"dialect": e["dialect"], "expression": e["expression"]}
                    for e in expressions
                ]
            }

        if field.get("is_time_dimension"):
            out["dimension"] = {"is_time": True}

        self._maybe_set(out, "label", field.get("label"))
        self._maybe_set(out, "description", field.get("description"))
        self._maybe_set(out, "ai_context", field.get("ai_context"))

        customs = self._customs_to_yaml(field.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _relationship_to_yaml(self, relationship: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": relationship["name"],
            "from": relationship["from"],
            "to": relationship["to"],
            "from_columns": list(relationship.get("from_columns") or []),
            "to_columns": list(relationship.get("to_columns") or []),
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
                    {"dialect": e["dialect"], "expression": e["expression"]}
                    for e in expressions
                ]
            }

        self._maybe_set(out, "description", metric.get("description"))
        self._maybe_set(out, "ai_context", metric.get("ai_context"))

        customs = self._customs_to_yaml(metric.get("custom_extensions"))
        if customs:
            out["custom_extensions"] = customs
        return out

    def _customs_to_yaml(self, customs: Any) -> list[dict[str, Any]]:
        """Reshape a list of {vendor_name, data} aspect dicts into OSI YAML form."""
        if not customs:
            return []
        return [
            {"vendor_name": c.get("vendor_name") or "", "data": c.get("data") or ""}
            for c in customs
            if c is not None
        ]

    @staticmethod
    def _maybe_set(target: dict[str, Any], key: str, value: Any) -> None:
        """Set ``target[key] = value`` only when ``value`` is non-empty / non-None."""
        if value in (None, "", [], {}):
            return
        target[key] = value
