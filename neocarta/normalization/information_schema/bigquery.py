"""BigQuery ``INFORMATION_SCHEMA`` adapter for the metadata normalizer.

Holds the Layer-1 concrete retriever and the Layer-2 declarative rename spec
that turn an already-populated :class:`BigQuerySchemaExtractor` into an
:class:`InformationSchemaTable`. Source-specific derivation (platform/service
injection, primary/foreign-key surfacing, foreign-key filtering, self-reference
skipping) lives here; type coercion stays in the record-model validators
(Layer 3), and deterministic ids/embeddings are generated later in the
graph-transform step — never here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    ReferenceRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)
from neocarta.normalization import MetadataNormalizer, RecordMapping

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    import pandas as pd

    from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
    from neocarta.normalization import NormalizationSpec

_PLATFORM = "GCP"
_SERVICE = "BIGQUERY"


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to row dicts, mapping ``NaN``/``NaT`` to ``None``.

    Args:
        frame: The source DataFrame; an empty frame yields an empty list.

    Returns:
        One dict per row keyed by column name, with missing values as ``None``.
    """
    if frame.empty:
        return []
    # ``astype(object)`` first so pandas neither re-coerces the ``None``s back to
    # ``NaN`` nor leaves numpy scalars (e.g. ``numpy.bool_``) in place; this also
    # avoids ``DataFrame.replace({np.nan: None})``, deprecated on recent pandas.
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


class BigQueryInformationSchemaRetriever:
    """Layer-1 retriever streaming BigQuery ``INFORMATION_SCHEMA`` rows.

    Wraps an already-populated :class:`BigQuerySchemaExtractor` (it performs no
    extraction) and structurally satisfies the ``Retriever`` protocol. It holds
    all source-specific derivation — injecting the ``platform``/``service``
    constants, surfacing the extractor's derived primary/foreign-key flags,
    filtering references to foreign keys, and dropping self-references — while
    leaving type coercion to the record models (Layer 3). It generates no ids.
    """

    def __init__(self, extractor: BigQuerySchemaExtractor) -> None:
        """Store the already-populated extractor to stream from."""
        self._extractor = extractor

    def stream(self, record_type: str) -> Iterable[dict[str, Any]]:
        """Yield flattened BigQuery rows for ``record_type`` (keyed by source names).

        Args:
            record_type: One of ``databases``, ``schemas``, ``tables``,
                ``columns``, ``references`` or ``values``.

        Returns:
            The source rows for ``record_type`` as dicts.

        Raises:
            ValueError: If ``record_type`` is not a known record type.
        """
        if record_type == "databases":
            return [
                {**row, "platform": _PLATFORM, "service": _SERVICE}
                for row in _frame_to_records(self._extractor.database_info)
            ]
        if record_type == "schemas":
            return _frame_to_records(self._extractor.schema_info)
        if record_type == "tables":
            return _frame_to_records(self._extractor.table_info)
        if record_type == "columns":
            # Streamed verbatim: is_primary_key/is_foreign_key are already derived on
            # the frame, and is_nullable stays raw ("YES"/"NO") so ColumnRecord's
            # validator (Layer 3) is the single place that decodes it. (The Retriever
            # protocol lists is_nullable decoding as layer-1; this adapter defers it.)
            return _frame_to_records(self._extractor.column_info)
        if record_type == "references":
            return [
                row
                for row in _frame_to_records(self._extractor.column_references_info)
                if row.get("constraint_type") == "FOREIGN KEY"
                and not (
                    row.get("table_name") == row.get("referenced_table")
                    and row.get("column_name") == row.get("referenced_column")
                )
            ]
        if record_type == "values":
            return _frame_to_records(self._extractor.column_unique_values)
        raise ValueError(f"Unknown record type: {record_type!r}")


BIGQUERY_INFORMATION_SCHEMA_SPEC: NormalizationSpec = [
    RecordMapping(
        record_type="databases",
        target_model=DatabaseRecord,
        mappings=[
            ("project_id", "database_name"),
            ("platform", "platform"),
            ("service", "service"),
        ],
        container_field="databases",
    ),
    RecordMapping(
        record_type="schemas",
        target_model=SchemaRecord,
        mappings=[
            ("project_id", "database_name"),
            ("dataset_id", "schema_name"),
            ("description", "description"),
        ],
        container_field="schemas",
    ),
    RecordMapping(
        record_type="tables",
        target_model=TableRecord,
        mappings=[
            ("table_catalog", "database_name"),
            ("table_schema", "schema_name"),
            ("table_name", "table_name"),
            ("table_type", "table_type"),
            ("description", "description"),
        ],
        container_field="tables",
    ),
    RecordMapping(
        record_type="columns",
        target_model=ColumnRecord,
        mappings=[
            ("table_catalog", "database_name"),
            ("table_schema", "schema_name"),
            ("table_name", "table_name"),
            ("column_name", "column_name"),
            ("data_type", "data_type"),
            ("is_nullable", "is_nullable"),
            ("is_primary_key", "is_primary_key"),
            ("is_foreign_key", "is_foreign_key"),
            ("description", "description"),
        ],
        container_field="columns",
    ),
    RecordMapping(
        record_type="references",
        target_model=ReferenceRecord,
        mappings=[
            ("constraint_catalog", "source_database_name"),
            ("constraint_schema", "source_schema_name"),
            ("table_name", "source_table_name"),
            ("column_name", "source_column_name"),
            ("constraint_catalog", "target_database_name"),
            ("constraint_schema", "target_schema_name"),
            ("referenced_table", "target_table_name"),
            ("referenced_column", "target_column_name"),
        ],
        container_field="references",
    ),
    RecordMapping(
        record_type="values",
        target_model=ValueRecord,
        mappings=[
            ("project_id", "database_name"),
            ("dataset_id", "schema_name"),
            ("table_name", "table_name"),
            ("column_name", "column_name"),
            ("unique_value", "value"),
        ],
        container_field="values",
    ),
]
"""BigQuery ``INFORMATION_SCHEMA`` → ``InformationSchemaTable`` declarative rename spec.

The ``references`` entry is why ``Mappings`` is an ordered list, not a dict:
``constraint_catalog`` and ``constraint_schema`` each feed two targets (the
source and target name-parts).
"""


def build_bigquery_information_schema_normalizer(
    extractor: BigQuerySchemaExtractor,
) -> MetadataNormalizer:
    """Build a normalizer over an already-populated BigQuery extractor.

    Args:
        extractor: An already-populated :class:`BigQuerySchemaExtractor`.

    Returns:
        A :class:`MetadataNormalizer` whose ``normalize()`` yields a populated
        :class:`InformationSchemaTable`.
    """
    return MetadataNormalizer(
        BigQueryInformationSchemaRetriever(extractor),
        BIGQUERY_INFORMATION_SCHEMA_SPEC,
        InformationSchemaTable,
    )
