"""Transform parsed Databricks metric-view definitions into OSI graph models.

A Unity Catalog metric view *is* a small semantic model (a source plus measures
and dimensions), so it maps onto neocarta's existing OSI nodes rather than new
ones — the same nodes the OSI YAML connector produces, populated from a
Databricks source:

- the metric view → an :class:`OsiSemanticModel` (a ``:Domain`` subtype), named
  by its three-part Unity Catalog path;
- the view as a dataset → an :class:`OsiTable` (``source`` = the three-part name,
  preserved as the lineage pointer for issue #210);
- each ``measure`` → a :class:`Metric` under the model (``HAS_METRIC``);
- each ``field`` / ``dimension`` → an :class:`OsiColumn` under the table
  (``HAS_COLUMN``);
- each measure / field ``expr`` → an :class:`Expression` (dialect ``databricks``);
- ``synonyms`` / ``display_name`` → an :class:`OsiAiContext` aspect, with
  ``synonyms`` additionally upserted as :class:`BusinessTerm` ``TAGGED_WITH``
  edges (the OSI loader MERGEs business terms by ``name``).

Physical backing-table/column lineage and ``joins`` are intentionally out of
scope for v1 (issue #210); the ``OsiTable.source`` string is preserved so that
follow-up can resolve them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ....data_model.glossary import BusinessTerm, TaggedWith
from ....data_model.osi import (
    DomainHasTable,
    Expression,
    HasAspect,
    HasExpression,
    HasMetric,
    Metric,
    OsiAiContext,
    OsiColumn,
    OsiSemanticModel,
    OsiTable,
)
from ....data_model.schema.rdbms import HasColumn
from ...utils.generate_id import (
    generate_ai_context_id,
    generate_business_term_id,
    generate_column_id,
    generate_expression_id,
    generate_metric_id,
    generate_osi_semantic_model_id,
    generate_table_id,
)

# Metric-view expressions are Databricks SQL.
_DIALECT = "databricks"

# OSI YAML metric views carry a ``version`` (the metric-view YAML spec version,
# e.g. "1.1"); we record it on the OsiSemanticModel.osi_version field. The field
# is required, so fall back to the current baseline if a definition omits it.
_DEFAULT_OSI_VERSION = "1.1"

# Synthetic glossary / category for BusinessTerms derived from metric-view
# synonyms. Matches the OSI connector's convention so synonyms from both
# connectors collapse to the same term (BusinessTerm is MERGEd by ``name`` at
# load time, so these segments only shape the id of a newly-created term).
_BT_GLOSSARY = "osi"
_BT_CATEGORY = "synonyms"

if TYPE_CHECKING:
    from .models import MetricViewInfo


class DatabricksMetricsTransformer:
    """Transform parsed metric-view definitions into OSI node/relationship models.

    The transformer owns instance-level caches that :class:`OsiNeo4jLoader`
    consumes. Call :meth:`transform` with the extractor's metric views to
    populate them.
    """

    def __init__(self) -> None:
        """Initialize the transformer with empty per-entity caches."""
        # Nodes
        self.osi_semantic_model_nodes: list[OsiSemanticModel] = []
        self.table_nodes: list[OsiTable] = []
        self.column_nodes: list[OsiColumn] = []
        self.metric_nodes: list[Metric] = []
        self.expression_nodes: list[Expression] = []
        self.ai_context_nodes: list[OsiAiContext] = []
        self.business_term_nodes: list[BusinessTerm] = []
        # Relationships
        self.domain_has_table_rels: list[DomainHasTable] = []
        self.has_column_rels: list[HasColumn] = []
        self.has_metric_rels: list[HasMetric] = []
        self.has_expression_rels: list[HasExpression] = []
        self.has_aspect_rels: list[HasAspect] = []
        self.tagged_with_rels: list[TaggedWith] = []
        # Dedupe state
        self._seen_expression_ids: set[str] = set()
        self._seen_aspect_ids: set[str] = set()
        self._seen_business_term_ids: set[str] = set()
        # Active metric view (the semantic-model name), used for aspect/metric id
        # generation without threading it through every call.
        self._current_sm_name: str = ""

    def _reset(self) -> None:
        """Clear all per-run caches so a reused transformer starts clean.

        The caches are instance-level and append-only, so without this a second
        :meth:`transform` (e.g. a second ``ingest`` on the same connector) would
        carry the previous run's nodes/relationships forward into the next load.
        """
        for cache in (
            self.osi_semantic_model_nodes,
            self.table_nodes,
            self.column_nodes,
            self.metric_nodes,
            self.expression_nodes,
            self.ai_context_nodes,
            self.business_term_nodes,
            self.domain_has_table_rels,
            self.has_column_rels,
            self.has_metric_rels,
            self.has_expression_rels,
            self.has_aspect_rels,
            self.tagged_with_rels,
        ):
            cache.clear()
        self._seen_expression_ids.clear()
        self._seen_aspect_ids.clear()
        self._seen_business_term_ids.clear()
        self._current_sm_name = ""

    def transform(self, metric_views: list[MetricViewInfo]) -> None:
        """Transform discovered metric views into graph nodes and relationships.

        Re-runnable: the per-run caches are reset at the start, so a reused
        transformer (e.g. a second ``ingest`` on the same connector) does not
        accumulate the previous run's output.

        Parameters
        ----------
        metric_views : list[MetricViewInfo]
            The metric views produced by
            :meth:`DatabricksMetricsExtractor.extract_metric_views`.
        """
        self._reset()
        for metric_view in metric_views:
            self._transform_metric_view(metric_view)

    # ------------------------------------------------------------------ #
    # Metric view → semantic model + table
    # ------------------------------------------------------------------ #

    def _transform_metric_view(self, metric_view: MetricViewInfo) -> None:
        full_name = metric_view["full_name"]
        catalog = metric_view["catalog"]
        schema = metric_view["schema"]
        name = metric_view["name"]
        definition = metric_view["definition"]
        self._current_sm_name = full_name

        version = definition.get("version")
        osi_version = str(version) if version is not None else _DEFAULT_OSI_VERSION
        description = definition.get("comment") or metric_view.get("comment")

        sm_id = generate_osi_semantic_model_id(full_name)
        self.osi_semantic_model_nodes.append(
            OsiSemanticModel(
                id=sm_id,
                name=full_name,
                description=description,
                osi_version=osi_version,
            )
        )

        # The metric view as a dataset. Its id intentionally coincides with the
        # semantic model's (both identify the same UC object from two roles —
        # they are distinct nodes by label); ``source`` is the lineage pointer.
        table_id = generate_table_id(catalog, schema, name)
        self.table_nodes.append(
            OsiTable(id=table_id, name=name, description=description, source=full_name)
        )
        self.domain_has_table_rels.append(DomainHasTable(domain_id=sm_id, table_id=table_id))

        # ``fields`` is preferred; ``dimensions`` is the accepted backward-compat synonym.
        fields = definition.get("fields")
        if fields is None:
            fields = definition.get("dimensions")
        for field in fields or []:
            self._transform_field(catalog, schema, name, table_id, field)

        for measure in definition.get("measures") or []:
            self._transform_measure(sm_id, measure)

    def _transform_field(
        self,
        catalog: str,
        schema: str,
        table_name: str,
        table_id: str,
        field: dict[str, Any],
    ) -> None:
        field_name = field["name"]
        column_id = generate_column_id(catalog, schema, table_name, field_name)
        # Metric-view fields declare no key/time-dimension metadata, so those
        # properties are left unset (None) and omitted at load time rather than
        # written as a fabricated False.
        self.column_nodes.append(
            OsiColumn(
                id=column_id,
                name=field_name,
                description=field.get("comment"),
                label=field.get("display_name"),
                is_primary_key=None,
                is_foreign_key=None,
                is_time_dimension=None,
            )
        )
        self.has_column_rels.append(HasColumn(table_id=table_id, column_id=column_id))
        self._add_expression(column_id, "Column", field.get("expr"))
        self._maybe_add_ai_context(column_id, "Column", _ai_context_payload(field))

    def _transform_measure(self, sm_id: str, measure: dict[str, Any]) -> None:
        measure_name = measure["name"]
        metric_id = generate_metric_id(self._current_sm_name, measure_name)
        self.metric_nodes.append(
            Metric(id=metric_id, name=measure_name, description=measure.get("comment"))
        )
        self.has_metric_rels.append(HasMetric(domain_id=sm_id, metric_id=metric_id))
        self._add_expression(metric_id, "Metric", measure.get("expr"))
        self._maybe_add_ai_context(metric_id, "Metric", _ai_context_payload(measure))

    # ------------------------------------------------------------------ #
    # Expressions and AI-context aspects (mirror the OSI ingest transformer)
    # ------------------------------------------------------------------ #

    def _add_expression(self, owner_id: str, owner_label: str, expression: Any) -> None:
        """Attach a Databricks-dialect Expression to a Column or Metric owner."""
        if not isinstance(expression, str) or not expression.strip():
            return
        expr_id = generate_expression_id(owner_id, _DIALECT, expression)
        if expr_id not in self._seen_expression_ids:
            self.expression_nodes.append(
                Expression(id=expr_id, dialect=_DIALECT, expression=expression)
            )
            self._seen_expression_ids.add(expr_id)
        self.has_expression_rels.append(
            HasExpression(source_label=owner_label, source_id=owner_id, expression_id=expr_id)
        )

    def _maybe_add_ai_context(
        self, source_id: str, source_label: str, payload: dict[str, Any] | None
    ) -> None:
        """Create an OsiAiContext aspect (and synonym BusinessTerms) for ``payload``.

        ``payload`` is the agent-facing metadata gathered from a measure/field
        (``synonyms`` / ``display_name``). The aspect id content-addresses the
        payload within the metric view, so identical payloads collapse to one
        Aspect node. Each synonym is also upserted as a :class:`BusinessTerm`
        with a ``TAGGED_WITH`` edge (Column and Metric are both tag-eligible).
        """
        if not payload:
            return
        data_str = json.dumps(payload, sort_keys=True)
        aspect_id = generate_ai_context_id(self._current_sm_name, data_str)
        if aspect_id not in self._seen_aspect_ids:
            self.ai_context_nodes.append(OsiAiContext(id=aspect_id, data=data_str))
            self._seen_aspect_ids.add(aspect_id)
        self.has_aspect_rels.append(
            HasAspect(source_label=source_label, source_id=source_id, aspect_id=aspect_id)
        )

        for synonym in payload.get("synonyms") or []:
            if not isinstance(synonym, str) or not synonym.strip():
                continue
            term_id = generate_business_term_id(_BT_GLOSSARY, _BT_CATEGORY, synonym)
            if term_id not in self._seen_business_term_ids:
                self.business_term_nodes.append(BusinessTerm(id=term_id, name=synonym))
                self._seen_business_term_ids.add(term_id)
            self.tagged_with_rels.append(
                TaggedWith(
                    source_label=source_label,
                    source_id=source_id,
                    business_term_id=term_id,
                )
            )


def _ai_context_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    """Build an AI-context mapping from a measure/field's agent metadata.

    Collects the metric-view ``synonyms`` (cleaned list) and ``display_name``
    into the JSON payload stored on an :class:`OsiAiContext` aspect. Returns
    ``None`` when neither is present so no empty aspect is created.
    """
    payload: dict[str, Any] = {}
    synonyms = item.get("synonyms")
    if isinstance(synonyms, list):
        # Strip each synonym and drop duplicates (order-preserving) so padded /
        # repeated variants don't produce divergent aspect ids or duplicate
        # BusinessTerms (e.g. " revenue " and "revenue").
        cleaned = list(
            dict.fromkeys(s.strip() for s in synonyms if isinstance(s, str) and s.strip())
        )
        if cleaned:
            payload["synonyms"] = cleaned
    display_name = item.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        payload["display_name"] = display_name.strip()
    return payload or None
