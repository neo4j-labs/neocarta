"""Transform a parsed OSI spec dict into graph node and relationship models."""

import json
import logging
import re
from typing import Any, TypedDict

from ....data_model.glossary import BusinessTerm, TaggedWith
from ....data_model.osi import (
    DomainHasTable,
    Expression,
    HasAspect,
    HasExpression,
    HasMetric,
    HasQuery,
    HasSourceTable,
    HasTargetTable,
    Join,
    Metric,
    MetricUsesColumn,
    MetricUsesTable,
    OsiAiContext,
    OsiColumn,
    OsiCustomExtensions,
    OsiSemanticModel,
    OsiTable,
    UsedInJoin,
)
from ....data_model.query import Query, UsesColumn
from ....data_model.schema.rdbms import (
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
)
from ...utils.generate_id import (
    _normalize,
    create_query_id,
    generate_ai_context_id,
    generate_business_term_id,
    generate_column_id,
    generate_custom_extension_id,
    generate_database_id,
    generate_expression_id,
    generate_join_id,
    generate_metric_id,
    generate_osi_semantic_model_id,
    generate_query_column_id,
    generate_schema_id,
    generate_table_id,
)
from .expression_refs import extract_references

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Synthetic glossary / category used for BusinessTerms derived from OSI ai_context
#: synonyms. BusinessTerm uniqueness in the graph is enforced by ``name`` at load
#: time (MERGE on name), so OSI synonyms can dedupe against catalog-derived BTs
#: regardless of their id format.
_OSI_BT_GLOSSARY = "osi"
_OSI_BT_CATEGORY = "synonyms"

#: Source labels the :class:`TaggedWith` model permits. OSI entities outside this
#: set (Domain, Query, Join) can still carry an :class:`OsiAiContext` aspect, but
#: their synonyms are not turned into BusinessTerm TAGGED_WITH edges.
_BT_TAGGABLE_LABELS = frozenset({"Column", "Table", "Schema", "Metric"})


class ParsedSource(TypedDict):
    """
    Parsed components of an OSI dataset ``source`` string.

    ``is_query`` discriminates the two shapes:
    - ``is_query=False``: ``table_name`` is set; ``query`` is ``None``. ``db_name``
      and ``schema_name`` are set when the source carried those components.
    - ``is_query=True``: ``query`` is set to the raw source text; ``db_name``,
      ``schema_name``, and ``table_name`` are all ``None``.
    """

    db_name: str | None
    schema_name: str | None
    table_name: str | None
    query: str | None
    is_query: bool


class OsiIngestTransformer:
    """
    Transform a parsed OSI YAML spec into pydantic node and relationship models.

    The transformer owns instance-level caches that downstream loaders consume.
    Call :meth:`transform` with the parsed OSI dict to populate them.
    """

    def __init__(self) -> None:
        """Initialize the transformer with empty per-entity caches."""
        # OSI top-level
        self.osi_semantic_model_nodes: list[OsiSemanticModel] = []
        # Structure
        self.database_nodes: list[Database] = []
        self.schema_nodes: list[Schema] = []
        self.table_nodes: list[OsiTable] = []
        self.column_nodes: list[OsiColumn] = []
        self.query_nodes: list[Query] = []
        # Semantic constructs
        self.metric_nodes: list[Metric] = []
        self.join_nodes: list[Join] = []
        self.expression_nodes: list[Expression] = []
        # Aspects
        self.ai_context_nodes: list[OsiAiContext] = []
        self.custom_extension_nodes: list[OsiCustomExtensions] = []
        # Business glossary (derived from aiContext.synonyms)
        self.business_term_nodes: list[BusinessTerm] = []
        # Relationships
        self.has_schema_rels: list[HasSchema] = []
        self.has_table_rels: list[HasTable] = []  # Schema → Table
        self.domain_has_table_rels: list[DomainHasTable] = []  # Domain → Table (:HAS_TABLE)
        self.has_query_rels: list[HasQuery] = []  # Domain → Query (:HAS_QUERY)
        self.has_column_rels: list[HasColumn] = []  # Table → Column
        # Query → Column uses :USES_COLUMN (existing query_log rel type).
        self.uses_column_rels: list[UsesColumn] = []
        self.references_rels: list[References] = []
        self.has_metric_rels: list[HasMetric] = []
        # Metric → backing table/column, derived by parsing metric expressions.
        self.metric_uses_table_rels: list[MetricUsesTable] = []
        self.metric_uses_column_rels: list[MetricUsesColumn] = []
        self.has_source_table_rels: list[HasSourceTable] = []
        self.has_target_table_rels: list[HasTargetTable] = []
        self.used_in_join_rels: list[UsedInJoin] = []
        self.has_expression_rels: list[HasExpression] = []
        self.has_aspect_rels: list[HasAspect] = []
        self.tagged_with_rels: list[TaggedWith] = []
        # Dedupe and resolution state
        self._seen_database_ids: set[str] = set()
        self._seen_schema_ids: set[str] = set()
        self._seen_business_term_ids: set[str] = set()
        self._seen_expression_ids: set[str] = set()
        self._seen_aspect_ids: set[str] = set()
        self._seen_metric_uses_table: set[tuple[str, str]] = set()
        self._seen_metric_uses_column: set[tuple[str, str]] = set()
        # Per-semantic-model: dataset name → backing node id, and dataset name → label
        # ("Table" or "Query"). Cleared at the start of each _transform_semantic_model.
        self._dataset_name_to_owner_id: dict[str, str] = {}
        self._dataset_name_to_owner_label: dict[str, str] = {}
        # Per-semantic-model set of materialized column ids, used to (a) emit
        # metric→column edges only for declared columns and (b) resolve unqualified
        # metric column references by candidate-id lookup. Cleared per semantic model.
        self._sm_column_ids: set[str] = set()
        # Active semantic model name. Set in _transform_semantic_model so aspect/metric/
        # join id generation can address it without parameter threading.
        self._current_sm_name: str = ""

    def transform(self, spec: dict[str, Any]) -> None:
        """
        Transform an OSI spec dict into graph nodes and relationships, populating
        the instance caches.

        Parameters
        ----------
        spec : dict[str, Any]
            The parsed OSI YAML document.
        """
        osi_version = str(spec.get("version", ""))
        for model in spec.get("semantic_model") or []:
            self._transform_semantic_model(model, osi_version)

    # ------------------------------------------------------------------ #
    # Semantic model
    # ------------------------------------------------------------------ #

    def _transform_semantic_model(self, model: dict[str, Any], osi_version: str) -> None:
        # Dataset-name resolution is scoped to a single semantic model: relationships
        # in one model never reference datasets defined in another.
        self._dataset_name_to_owner_id = {}
        self._dataset_name_to_owner_label = {}
        self._sm_column_ids = set()

        sm_name = model["name"]
        self._current_sm_name = sm_name

        sm_id = generate_osi_semantic_model_id(sm_name)
        sm = OsiSemanticModel(
            id=sm_id,
            name=sm_name,
            description=model.get("description"),
            osi_version=osi_version,
        )
        self.osi_semantic_model_nodes.append(sm)

        datasets = model.get("datasets") or []
        relationships = model.get("relationships") or []

        # Pre-scan dataset sources so relationship FK resolution can produce column ids
        # before we materialize any OsiColumn nodes.
        for dataset in datasets:
            owner_id, owner_label = self._resolve_dataset_owner(dataset["source"])
            self._dataset_name_to_owner_id[dataset["name"]] = owner_id
            self._dataset_name_to_owner_label[dataset["name"]] = owner_label

        foreign_key_column_ids = self._collect_foreign_key_column_ids(relationships)

        for dataset in datasets:
            self._transform_dataset(sm.id, dataset, foreign_key_column_ids)
        for relationship in relationships:
            self._transform_relationship(relationship)
        for metric in model.get("metrics", []) or []:
            self._transform_metric(sm.id, metric)

        # Semantic-model-level aspects.
        self._maybe_add_ai_context(
            source_id=sm.id, source_label="Domain", value=model.get("ai_context")
        )
        self._add_custom_extensions(
            source_id=sm.id, source_label="Domain", extensions=model.get("custom_extensions")
        )

    def _collect_foreign_key_column_ids(self, relationships: list[dict[str, Any]]) -> set[str]:
        """
        Pre-scan relationships to derive the set of foreign-key column ids.

        OSI relationships are foreign-key-style links from the ``from`` dataset's
        columns (the FK side) to the ``to`` dataset's primary/unique key columns.
        Only the ``from_columns`` are FKs.
        """
        fk_ids: set[str] = set()
        for relationship in relationships:
            from_dataset = relationship.get("from")
            from_owner_id = self._dataset_name_to_owner_id.get(from_dataset)
            if not from_owner_id:
                continue
            from_owner_label = self._dataset_name_to_owner_label.get(from_dataset, "Table")
            for col_name in relationship.get("from_columns") or []:
                fk_ids.add(self._make_column_id(from_owner_id, from_owner_label, col_name))
        return fk_ids

    # ------------------------------------------------------------------ #
    # Datasets and fields
    # ------------------------------------------------------------------ #

    def _transform_dataset(
        self,
        sm_id: str,
        dataset: dict[str, Any],
        foreign_key_column_ids: set[str],
    ) -> None:
        name = dataset["name"]
        source = dataset["source"]
        parsed = self._parse_source(source)

        if parsed["is_query"]:
            owner_id, owner_label = self._materialize_query_dataset(
                sm_id, dataset, parsed["query"] or ""
            )
        else:
            # _parse_source guarantees these are non-None when is_query=False.
            owner_id, owner_label = self._materialize_table_dataset(
                sm_id,
                dataset,
                parsed["db_name"],  # type: ignore[arg-type]
                parsed["schema_name"],  # type: ignore[arg-type]
                parsed["table_name"],  # type: ignore[arg-type]
            )
        self._dataset_name_to_owner_id[name] = owner_id
        self._dataset_name_to_owner_label[name] = owner_label

        self._maybe_add_ai_context(
            source_id=owner_id, source_label=owner_label, value=dataset.get("ai_context")
        )
        self._add_custom_extensions(
            source_id=owner_id,
            source_label=owner_label,
            extensions=dataset.get("custom_extensions"),
        )

        primary_key = dataset.get("primary_key") or []
        primary_key_columns = set(primary_key)
        for field in dataset.get("fields") or []:
            self._transform_field(
                owner_id, owner_label, field, primary_key_columns, foreign_key_column_ids
            )

    def _materialize_table_dataset(
        self,
        sm_id: str,
        dataset: dict[str, Any],
        db_name: str,
        schema_name: str,
        table_name: str,
    ) -> tuple[str, str]:
        """
        Create the OsiTable, Database, Schema, and structural edges for a
        spec-compliant 3-part dataset source.

        ``_parse_source`` enforces that ``db_name`` / ``schema_name`` / ``table_name``
        are all non-empty identifiers before this is called.
        """
        source = dataset["source"]
        table_id_str = generate_table_id(db_name, schema_name, table_name)

        db_id_str = generate_database_id(db_name)
        if db_id_str not in self._seen_database_ids:
            self.database_nodes.append(Database(id=db_id_str, name=db_name))
            self._seen_database_ids.add(db_id_str)

        schema_id_str = generate_schema_id(db_name, schema_name)
        if schema_id_str not in self._seen_schema_ids:
            self.schema_nodes.append(Schema(id=schema_id_str, name=schema_name))
            self._seen_schema_ids.add(schema_id_str)
            self.has_schema_rels.append(HasSchema(database_id=db_id_str, schema_id=schema_id_str))
        self.has_table_rels.append(HasTable(schema_id=schema_id_str, table_id=table_id_str))

        primary_key = dataset.get("primary_key") or None
        unique_keys = dataset.get("unique_keys")
        if unique_keys:
            unique_keys = [uk for uk in unique_keys if uk]
            if not unique_keys:
                unique_keys = None
        self.table_nodes.append(
            OsiTable(
                id=table_id_str,
                name=dataset["name"],
                description=dataset.get("description"),
                source=source,
                primary_key=primary_key,
                unique_keys=unique_keys,
            )
        )
        self.domain_has_table_rels.append(DomainHasTable(domain_id=sm_id, table_id=table_id_str))
        return table_id_str, "Table"

    def _materialize_query_dataset(
        self, sm_id: str, dataset: dict[str, Any], source: str
    ) -> tuple[str, str]:
        """Create the Query node and Domain→Query edge for a query-backed dataset."""
        query_id_str = create_query_id(source)
        self.query_nodes.append(
            Query(
                id=query_id_str,
                name=dataset["name"],
                content=source,
                description=dataset.get("description"),
            )
        )
        self.has_query_rels.append(HasQuery(domain_id=sm_id, query_id=query_id_str))
        return query_id_str, "Query"

    def _transform_field(
        self,
        owner_id: str,
        owner_label: str,
        field: dict[str, Any],
        primary_key_columns: set[str],
        foreign_key_column_ids: set[str],
    ) -> None:
        field_name = field["name"]
        column_id_str = self._make_column_id(owner_id, owner_label, field_name)
        # Track declared column ids for this semantic model so metric-expression parsing
        # can emit USES_COLUMN edges only for columns that actually exist as nodes.
        self._sm_column_ids.add(column_id_str)

        # Only persist is_time_dimension when the OSI field explicitly declares
        # ``dimension.is_time`` as a bool. Missing / non-bool values leave the
        # property unset on the graph node so the absence round-trips cleanly.
        dimension = field.get("dimension")
        is_time_value = dimension.get("is_time") if isinstance(dimension, dict) else None
        is_time_dimension: bool | None = is_time_value if isinstance(is_time_value, bool) else None

        self.column_nodes.append(
            OsiColumn(
                id=column_id_str,
                name=field_name,
                description=field.get("description"),
                label=field.get("label"),
                is_primary_key=field_name in primary_key_columns,
                is_foreign_key=column_id_str in foreign_key_column_ids,
                is_time_dimension=is_time_dimension,
            )
        )
        if owner_label == "Query":
            self.uses_column_rels.append(UsesColumn(query_id=owner_id, column_id=column_id_str))
        else:
            self.has_column_rels.append(HasColumn(table_id=owner_id, column_id=column_id_str))

        for dialect_entry in ((field.get("expression") or {}).get("dialects")) or []:
            self._add_expression(
                owner_id=column_id_str,
                owner_label="Column",
                dialect=dialect_entry.get("dialect"),
                expression=dialect_entry.get("expression"),
            )

        self._maybe_add_ai_context(
            source_id=column_id_str, source_label="Column", value=field.get("ai_context")
        )
        self._add_custom_extensions(
            source_id=column_id_str,
            source_label="Column",
            extensions=field.get("custom_extensions"),
        )

    # ------------------------------------------------------------------ #
    # Relationships (Join nodes)
    # ------------------------------------------------------------------ #

    def _transform_relationship(self, relationship: dict[str, Any]) -> None:
        rel_name = relationship["name"]
        join_id_str = generate_join_id(self._current_sm_name, rel_name)

        from_columns = list(relationship.get("from_columns") or [])
        to_columns = list(relationship.get("to_columns") or [])

        self.join_nodes.append(
            Join(
                id=join_id_str,
                name=rel_name,
                from_columns=from_columns or None,
                to_columns=to_columns or None,
            )
        )

        from_owner_id = self._dataset_name_to_owner_id.get(relationship.get("from"))
        to_owner_id = self._dataset_name_to_owner_id.get(relationship.get("to"))
        from_owner_label = self._dataset_name_to_owner_label.get(relationship.get("from"), "Table")
        to_owner_label = self._dataset_name_to_owner_label.get(relationship.get("to"), "Table")

        # HasSourceTable / HasTargetTable point at the dataset's backing node id.
        # When that node is a Query (rather than a Table), the rel still resolves
        # by id at load time; the target type asymmetry is tolerated for now.
        if from_owner_id:
            self.has_source_table_rels.append(
                HasSourceTable(join_id=join_id_str, table_id=from_owner_id)
            )
        if to_owner_id:
            self.has_target_table_rels.append(
                HasTargetTable(join_id=join_id_str, table_id=to_owner_id)
            )

        if from_owner_id:
            for col_name in from_columns:
                self.used_in_join_rels.append(
                    UsedInJoin(
                        column_id=self._make_column_id(from_owner_id, from_owner_label, col_name),
                        join_id=join_id_str,
                    )
                )
        if to_owner_id:
            for col_name in to_columns:
                self.used_in_join_rels.append(
                    UsedInJoin(
                        column_id=self._make_column_id(to_owner_id, to_owner_label, col_name),
                        join_id=join_id_str,
                    )
                )

        # OSI relationships are foreign-key-like; emit positional References edges
        # between paired from/to columns so existing graph consumers see the FK link.
        # Per OSI spec, from_columns and to_columns must have the same length —
        # strict=True surfaces malformed input rather than silently truncating.
        if from_owner_id and to_owner_id:
            for from_col, to_col in zip(from_columns, to_columns, strict=True):
                self.references_rels.append(
                    References(
                        source_column_id=self._make_column_id(
                            from_owner_id, from_owner_label, from_col
                        ),
                        target_column_id=self._make_column_id(to_owner_id, to_owner_label, to_col),
                    )
                )

        self._add_custom_extensions(
            source_id=join_id_str,
            source_label="Join",
            extensions=relationship.get("custom_extensions"),
        )

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #

    def _transform_metric(self, sm_id: str, metric: dict[str, Any]) -> None:
        metric_name = metric["name"]
        metric_id_str = generate_metric_id(self._current_sm_name, metric_name)
        self.metric_nodes.append(
            Metric(id=metric_id_str, name=metric_name, description=metric.get("description"))
        )
        self.has_metric_rels.append(HasMetric(domain_id=sm_id, metric_id=metric_id_str))

        for dialect_entry in ((metric.get("expression") or {}).get("dialects")) or []:
            self._add_expression(
                owner_id=metric_id_str,
                owner_label="Metric",
                dialect=dialect_entry.get("dialect"),
                expression=dialect_entry.get("expression"),
            )

        self._link_metric_backing(metric_id_str, metric)

        self._maybe_add_ai_context(
            source_id=metric_id_str, source_label="Metric", value=metric.get("ai_context")
        )
        self._add_custom_extensions(
            source_id=metric_id_str,
            source_label="Metric",
            extensions=metric.get("custom_extensions"),
        )

    def _link_metric_backing(self, metric_id: str, metric: dict[str, Any]) -> None:
        """
        Emit ``(:Metric)-[:USES_TABLE]->`` / ``(:Metric)-[:USES_COLUMN]->`` edges for the
        datasets and columns a metric's expressions reference.

        Each dialect expression is parsed with :func:`extract_references`, which returns the
        table and column references (aliases resolved, stars captured). Qualifiers are
        resolved against the current semantic model as dataset names or ``db.schema.table``
        source paths; unqualified columns are matched by name across the model's datasets.
        A USES_TABLE edge is emitted for every resolved table reference; a USES_COLUMN edge
        only when the column is a declared field of that dataset (so it has a graph node to
        point at). Non-SQL / unparseable expressions and unresolvable references are skipped
        (logged at debug), never failing the ingest.
        """
        owner_labels = self._owner_id_to_label()
        for dialect_entry in ((metric.get("expression") or {}).get("dialects")) or []:
            expression = dialect_entry.get("expression")
            if not expression:
                continue
            refs = extract_references(expression, dialect_entry.get("dialect"))
            if refs is None:  # non-SQL dialect / unparseable — extract_references logged it
                continue
            # USES_TABLE for every referenced dataset (incl. FROM tables and star refs).
            for qualifier in refs.tables:
                owner = self._resolve_qualifier(qualifier, owner_labels)
                if owner is not None:
                    self._add_metric_uses_table(metric_id, owner[0])
            # USES_COLUMN (and USES_TABLE) for each concrete column reference.
            for qualifier, column_name in refs.columns:
                owner = (
                    self._resolve_qualifier(qualifier, owner_labels)
                    if qualifier is not None
                    else self._resolve_unqualified_column(column_name)
                )
                if owner is None:
                    continue
                owner_id, owner_label = owner
                self._add_metric_uses_table(metric_id, owner_id)
                column_id = self._make_column_id(owner_id, owner_label, column_name)
                if column_id in self._sm_column_ids:
                    self._add_metric_uses_column(metric_id, column_id)

    def _owner_id_to_label(self) -> dict[str, str]:
        """Reverse of the dataset maps: backing-node id → ``"Table"`` / ``"Query"``."""
        return {
            owner_id: self._dataset_name_to_owner_label.get(ds_name, "Table")
            for ds_name, owner_id in self._dataset_name_to_owner_id.items()
        }

    def _resolve_qualifier(
        self, qualifier: str, owner_labels: dict[str, str]
    ) -> tuple[str, str] | None:
        """
        Resolve a table qualifier to its dataset's ``(owner_id, owner_label)``.

        Tries, in order: an exact dataset-name match; a normalized dataset-name match
        (case/separator-insensitive via :func:`_normalize`, since ids are normalized
        everywhere else); and — for a 3-part ``database.schema.table`` source path — the
        corresponding table id. Returns ``None`` when nothing matches.
        """
        owner_id = self._dataset_name_to_owner_id.get(qualifier)
        if owner_id is not None:
            return owner_id, self._dataset_name_to_owner_label.get(qualifier, "Table")

        normalized = _normalize(qualifier)
        for ds_name, ds_owner_id in self._dataset_name_to_owner_id.items():
            if _normalize(ds_name) == normalized:
                return ds_owner_id, self._dataset_name_to_owner_label.get(ds_name, "Table")

        parts = qualifier.split(".")
        if len(parts) == 3:  # a database.schema.table source-path reference
            candidate = generate_table_id(parts[0], parts[1], parts[2])
            label = owner_labels.get(candidate)
            if label is not None:
                return candidate, label
        return None

    def _resolve_unqualified_column(self, column_name: str) -> tuple[str, str] | None:
        """
        Resolve an unqualified column to its dataset's ``(owner_id, owner_label)``.

        A dataset owns the column iff its candidate column id was materialized. Matching
        DATASETS are counted (one entry per dataset, not per distinct owner id) so two
        dataset aliases backed by the same table/query stay ambiguous; resolves only when
        exactly one dataset declares the column.
        """
        matches: list[tuple[str, str]] = []
        for ds_name, ds_owner_id in self._dataset_name_to_owner_id.items():
            ds_owner_label = self._dataset_name_to_owner_label.get(ds_name, "Table")
            if (
                self._make_column_id(ds_owner_id, ds_owner_label, column_name)
                in self._sm_column_ids
            ):
                matches.append((ds_owner_id, ds_owner_label))
        return matches[0] if len(matches) == 1 else None

    def _add_metric_uses_table(self, metric_id: str, table_id: str) -> None:
        """Append a deduped ``MetricUsesTable`` edge (owner may be a Table or Query node)."""
        key = (metric_id, table_id)
        if key in self._seen_metric_uses_table:
            return
        self._seen_metric_uses_table.add(key)
        self.metric_uses_table_rels.append(MetricUsesTable(metric_id=metric_id, table_id=table_id))

    def _add_metric_uses_column(self, metric_id: str, column_id: str) -> None:
        """Append a deduped ``MetricUsesColumn`` edge."""
        key = (metric_id, column_id)
        if key in self._seen_metric_uses_column:
            return
        self._seen_metric_uses_column.add(key)
        self.metric_uses_column_rels.append(
            MetricUsesColumn(metric_id=metric_id, column_id=column_id)
        )

    # ------------------------------------------------------------------ #
    # Aspects: AI context and custom extensions
    # ------------------------------------------------------------------ #

    def _maybe_add_ai_context(self, source_id: str, source_label: str, value: Any) -> None:
        """
        Create an OsiAiContext aspect for ``source_id`` if ``value`` is present.

        The aspect id is ``{semantic_model_name}.{hash(data)}`` so identical AI
        context payloads under the same semantic model collapse to one Aspect
        node referenced by every entity that shares the content.

        If the AI context payload parses as a JSON dict with a ``synonyms`` array,
        each synonym is also upserted as a :class:`BusinessTerm` and a TAGGED_WITH
        edge is created from the OSI entity. Final BusinessTerm uniqueness in the
        graph is enforced by ``name`` at load time (MERGE on name), so OSI
        synonyms can dedupe against catalog-derived BTs from other connectors.
        """
        if value in (None, ""):
            return

        if isinstance(value, str):
            data_str = value
            parsed = self._try_parse_json(value)
        else:
            data_str = json.dumps(value, sort_keys=True)
            parsed = value if isinstance(value, dict) else None

        aspect_id_str = generate_ai_context_id(self._current_sm_name, data_str)
        if aspect_id_str not in self._seen_aspect_ids:
            self.ai_context_nodes.append(OsiAiContext(id=aspect_id_str, data=data_str))
            self._seen_aspect_ids.add(aspect_id_str)
        self.has_aspect_rels.append(
            HasAspect(source_label=source_label, source_id=source_id, aspect_id=aspect_id_str)
        )

        if not isinstance(parsed, dict):
            return
        synonyms = parsed.get("synonyms")
        if not isinstance(synonyms, list):
            return
        # Only Schema / Table / Column / Metric can carry TaggedWith per the data
        # model; Domain / Query / Join still get the OsiAiContext aspect above but
        # do not propagate synonyms into BusinessTerm tags.
        if source_label not in _BT_TAGGABLE_LABELS:
            return
        for synonym in synonyms:
            if not isinstance(synonym, str) or not synonym.strip():
                continue
            term_id = generate_business_term_id(_OSI_BT_GLOSSARY, _OSI_BT_CATEGORY, synonym)
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

    def _add_custom_extensions(self, source_id: str, source_label: str, extensions: Any) -> None:
        if not extensions:
            return
        for ext in extensions:
            if not isinstance(ext, dict):
                continue
            vendor = ext.get("vendor_name") or ""
            payload = ext.get("data")
            if payload is None:
                continue
            data_str = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
            ext_id_str = generate_custom_extension_id(self._current_sm_name, vendor, data_str)
            if ext_id_str not in self._seen_aspect_ids:
                self.custom_extension_nodes.append(
                    OsiCustomExtensions(id=ext_id_str, vendor_name=vendor, data=data_str)
                )
                self._seen_aspect_ids.add(ext_id_str)
            self.has_aspect_rels.append(
                HasAspect(source_label=source_label, source_id=source_id, aspect_id=ext_id_str)
            )

    # ------------------------------------------------------------------ #
    # Expressions
    # ------------------------------------------------------------------ #

    def _add_expression(
        self,
        owner_id: str,
        owner_label: str,
        dialect: str | None,
        expression: str | None,
    ) -> None:
        if dialect is None or expression is None:
            return
        expr_id = generate_expression_id(owner_id, dialect, expression)
        if expr_id not in self._seen_expression_ids:
            self.expression_nodes.append(
                Expression(id=expr_id, dialect=dialect, expression=expression)
            )
            self._seen_expression_ids.add(expr_id)
        self.has_expression_rels.append(
            HasExpression(source_label=owner_label, source_id=owner_id, expression_id=expr_id)
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _resolve_dataset_owner(self, source: str) -> tuple[str, str]:
        """
        Compute the owner id and label (``"Table"`` / ``"Query"``) for a dataset's
        backing graph node without emitting any nodes.

        Used during the pre-scan so relationship FK resolution can produce column
        ids before fields are materialized. :meth:`_parse_source` guarantees that
        when ``is_query=False`` all three structural fields are set.
        """
        parsed = self._parse_source(source)
        if parsed["is_query"]:
            return create_query_id(parsed["query"] or ""), "Query"
        return (
            generate_table_id(
                parsed["db_name"],  # type: ignore[arg-type]
                parsed["schema_name"],  # type: ignore[arg-type]
                parsed["table_name"],  # type: ignore[arg-type]
            ),
            "Table",
        )

    def _make_column_id(self, owner_id: str, owner_label: str, column_name: str) -> str:
        """
        Build a column id under a Table or Query owner.

        Routes through the appropriate centralized id generator: Table owners go
        through :func:`generate_column_id` (re-splitting the dotted table id back
        into its db/schema/table segments); Query owners go through
        :func:`generate_query_column_id` (since query ids are opaque hashes).
        """
        if owner_label == "Query":
            return generate_query_column_id(owner_id, column_name)
        parts = owner_id.split(".")
        db, schema, table = parts[0], parts[1], ".".join(parts[2:])
        return generate_column_id(db, schema, table, column_name)

    def _parse_source(self, source: str) -> ParsedSource:
        """
        Parse an OSI ``source`` string into a :class:`ParsedSource` discriminated
        on ``is_query``.

        Per the OSI spec, ``dataset.source`` must be either a 3-part
        ``database.schema.table`` identifier or a SQL query. 1-part and 2-part
        dotted identifiers are spec violations and raise :class:`ValueError`.
        Anything that isn't valid SQL identifiers (multi-token text, special
        characters, etc.) is treated as a query.

        Raises:
        ------
        ValueError
            If ``source`` is empty or is a 1-part / 2-part dotted identifier.
        """
        if not source:
            raise ValueError("dataset.source must not be empty")

        parts = source.split(".")
        all_identifiers = all(_IDENT_RE.match(part) for part in parts)

        if len(parts) == 3 and all_identifiers:
            db, schema, table = parts
            return {
                "db_name": db,
                "schema_name": schema,
                "table_name": table,
                "query": None,
                "is_query": False,
            }

        if 1 <= len(parts) <= 2 and all_identifiers:
            raise ValueError(
                f"dataset.source {source!r} is not OSI-spec-compliant: must be "
                "either a 3-part `database.schema.table` identifier or a SQL query."
            )

        return {
            "db_name": None,
            "schema_name": None,
            "table_name": None,
            "query": source,
            "is_query": True,
        }

    def _try_parse_json(self, value: str) -> Any | None:
        try:
            return json.loads(value)
        except (ValueError, json.JSONDecodeError):
            return None
