"""The BigQuery schema connector's normalized-schema mapping declaration.

Replaces the mapping half of [`transform.py`](transform.py) (466 lines, 10 families). Every field
binds through the ratified vocabulary with **no renames**: ``project_id`` and ``table_catalog``
are container synonyms, ``data_type`` and ``is_nullable`` are canonical, and the foreign-key
frame's ``constraint_catalog`` / ``constraint_schema`` / ``referenced_*`` bind to the role-scoped
FK aliases.

That last one faithfully reproduces this connector's *existing* behaviour of deriving **both**
endpoints from ``constraint_*``, so a cross-dataset foreign key names the wrong target catalog.
The defect is inside the committed golden, so parity means reproducing it; fixing it is its own
ticket, with the golden diff as the record
([mapping-mechanism.md](../../../../docs/refactor/mapping-mechanism.md) §5.1).

Declared alongside the hand-written transformer, not replacing it: the connector still runs its
own ``transform.py`` until the S4 cutover (GUIDE §2, additive dual-path).
"""

from collections.abc import Mapping
from typing import Any

from neocarta.etl.metadata_normalizer import ConnectorMapping, SourceTable, container_path_from
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)


def _is_foreign_key(row: Mapping[str, Any]) -> bool:
    """Keep only true foreign-key constraints from a mixed constraint frame."""
    return row.get("constraint_type") == "FOREIGN KEY"


#: The ``pre_fold`` hatch, and a real gap rather than a fixture artefact: the value frame is
#: declared as exactly ``[column_name, unique_value, column_id, value_id]`` in ``extract.py``,
#: while ``ValueRecord`` is addressed by its full natural key.
_VALUE_CONTAINER_PATH = container_path_from(
    "column_id", ("database_name", "schema_name", "table_name"), id_segments=4
)

BIGQUERY_SCHEMA = ConnectorMapping(
    tables={
        "databases": SourceTable(
            record=DatabaseRecord,
            source="database_info",
            constants={"platform": "GCP", "service": "BIGQUERY"},
        ),
        "schemas": SourceTable(record=SchemaRecord, source="schema_info"),
        "tables": SourceTable(record=TableRecord, source="table_info"),
        "columns": SourceTable(record=ColumnRecord, source="column_info"),
        "values": SourceTable(
            record=ValueRecord,
            source="column_unique_values",
            project=_VALUE_CONTAINER_PATH,
        ),
        "foreign_keys": SourceTable(
            record=ForeignKeyRecord,
            source="column_references_info",
            row_filter=_is_foreign_key,
        ),
    },
    drop_self_references=True,
)
