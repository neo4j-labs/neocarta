"""Pure statement builders for turning a table spec into real tables.

Both the dense-schema and schemapile examples once carried near-identical copies
of the create-schema, create-table, insert-rows, add-constraints sequence and
its supporting helpers. This module is the single home for that plumbing, and it
is deliberately *pure*: it only builds SQL strings (and the small records the
foreign-key pass needs). It opens nothing, spawns no threads, and runs no SQL.

The imperative shell that owns a ``SparkSession`` (the ``dbxcarta-materialize``
Spark job) asks these builders for the statements, runs them with ``spark.sql``,
pools the independent table creates, and tallies the run. Keeping execution and
threading out of core makes the builders trivially testable as text and leaves
the only thread pool over a known thread-safe ``SparkSession``.

Example choices (the source type map and the table-property prefix) are passed
in as arguments rather than hardcoded, so one copy serves every example.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from dbxcarta.core.identifiers import quote_identifier

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_CONSTRAINT_NAME_LIMIT = 255

_DECIMAL_RE = re.compile(r"^(?:DECIMAL|NUMERIC|NUMBER|DEC)\s*\((\d+)\s*,\s*(\d+)\)$")
_VARCHAR_RE = re.compile(r"^(?:VARCHAR|CHAR|CHARACTER|NVARCHAR|NCHAR)\s*\(\s*\d+\s*\)$")
_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]+")

# The one shared source-type -> Delta-type map. Both examples carried this map
# with identical entries, so core owns it as the default. An example overrides
# it only if its source ever needs different entries; this keeps a single map
# today without hardcoding that the two sources must always agree.
DEFAULT_DELTA_TYPE_MAP: Mapping[str, str] = MappingProxyType(
    {
        "INT": "INT",
        "INTEGER": "INT",
        "INT4": "INT",
        "BIGINT": "BIGINT",
        "INT8": "BIGINT",
        "LONG": "BIGINT",
        "SMALLINT": "SMALLINT",
        "TINYINT": "TINYINT",
        "MEDIUMINT": "INT",
        # Spark has no unsigned integers; widen each to the next signed type
        # that holds the full unsigned range without overflow.
        "UNSIGNEDTINYINT": "SMALLINT",
        "UNSIGNEDSMALLINT": "INT",
        "UNSIGNEDMEDIUMINT": "INT",
        "UNSIGNEDINT": "BIGINT",
        "UNSIGNEDINTEGER": "BIGINT",
        "UNSIGNEDBIGINT": "DECIMAL(20,0)",
        # Postgres auto-increment aliases.
        "SERIAL": "BIGINT",
        "BIGSERIAL": "BIGINT",
        "SMALLSERIAL": "INT",
        "FLOAT": "FLOAT",
        "REAL": "FLOAT",
        "DOUBLE": "DOUBLE",
        "DOUBLE PRECISION": "DOUBLE",
        "DECIMAL": "DECIMAL(18,4)",
        "NUMERIC": "DECIMAL(18,4)",
        "NUMBER": "DECIMAL(18,4)",
        "MONEY": "DECIMAL(18,4)",
        "BOOLEAN": "BOOLEAN",
        "BOOL": "BOOLEAN",
        "BIT": "BOOLEAN",
        "TEXT": "STRING",
        "LONGTEXT": "STRING",
        "MEDIUMTEXT": "STRING",
        "TINYTEXT": "STRING",
        "CHARACTER VARYING": "STRING",
        "VARCHAR": "STRING",
        "VARCHAR2": "STRING",
        "CHAR": "STRING",
        "NVARCHAR": "STRING",
        "NCHAR": "STRING",
        "STRING": "STRING",
        "CLOB": "STRING",
        "DATE": "DATE",
        "DATETIME": "TIMESTAMP",
        "TIMESTAMP": "TIMESTAMP",
        "TIMESTAMPTZ": "TIMESTAMP",
        "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
        "TIME": "STRING",
        "TIME WITHOUT TIME ZONE": "STRING",
        "BLOB": "BINARY",
        "TINYBLOB": "BINARY",
        "MEDIUMBLOB": "BINARY",
        "LONGBLOB": "BINARY",
        "BINARY": "BINARY",
        "VARBINARY": "BINARY",
        "BYTEA": "BINARY",
        "JSON": "STRING",
        "JSONB": "STRING",
        "UUID": "STRING",
        "ENUM": "STRING",
        "SET": "STRING",
    }
)


@dataclass
class MaterializeStats:
    """Tally of one materialize run.

    Holds counts only. Parallelism is the shell's concern: a parallel
    materialize has each table build return its own ``MaterializeStats`` and the
    shell sums them with :meth:`__add__`, so the shape carries no shared mutable
    state. Core fills the build-time counts (``type_fallbacks`` and the
    ``tables_skipped`` of a build-time skip); the shell adds the runtime counts
    (``tables_created``, ``rows_inserted``, ``pk_constraints_added``,
    ``fk_constraints_added``) as each statement it runs succeeds.
    """

    schemas_created: int = 0
    tables_created: int = 0
    rows_inserted: int = 0
    tables_skipped: int = 0
    type_fallbacks: int = 0
    pk_constraints_added: int = 0
    fk_constraints_added: int = 0

    def __add__(self, other: MaterializeStats) -> MaterializeStats:
        if not isinstance(other, MaterializeStats):
            return NotImplemented
        return MaterializeStats(
            schemas_created=self.schemas_created + other.schemas_created,
            tables_created=self.tables_created + other.tables_created,
            rows_inserted=self.rows_inserted + other.rows_inserted,
            tables_skipped=self.tables_skipped + other.tables_skipped,
            type_fallbacks=self.type_fallbacks + other.type_fallbacks,
            pk_constraints_added=self.pk_constraints_added + other.pk_constraints_added,
            fk_constraints_added=self.fk_constraints_added + other.fk_constraints_added,
        )


def coerce_type(raw: str, type_map: Mapping[str, str] = DEFAULT_DELTA_TYPE_MAP) -> tuple[str, bool]:
    """Map a source column type to a Delta type.

    Returns ``(delta_type, fellback)`` where ``fellback`` is True when the type
    could not be matched and defaulted to ``STRING``. ``DECIMAL(p, s)`` is
    clamped to Delta's bounds; sized ``VARCHAR``/``CHAR`` becomes ``STRING``.
    Matching is whitespace-insensitive, so a CamelCase source type such as
    ``DoublePrecision`` resolves to the same entry as ``DOUBLE PRECISION``.
    """
    if not raw:
        return "STRING", True
    normalized = raw.upper().strip().strip(";").strip()
    decimal_match = _DECIMAL_RE.match(normalized)
    if decimal_match:
        precision = max(1, min(int(decimal_match.group(1)), 38))
        scale = max(0, min(int(decimal_match.group(2)), precision))
        return f"DECIMAL({precision},{scale})", False
    if _VARCHAR_RE.match(normalized):
        return "STRING", False
    if normalized in type_map:
        return type_map[normalized], False
    base = normalized.split("(", 1)[0].strip()
    if base in type_map:
        return type_map[base], False
    collapsed = base.replace(" ", "")
    despaced = {key.replace(" ", ""): value for key, value in type_map.items()}
    if collapsed in despaced:
        return despaced[collapsed], False
    return "STRING", True


def sanitize_identifier(name: str, *, prefix: str = "t") -> str:
    """Clean a name into a legal identifier.

    Non-identifier runs collapse to ``_``; the result is stripped of leading
    and trailing underscores and lowercased. A cleaned name that starts with a
    digit is prefixed with ``f"{prefix}_"`` so it is a legal identifier. Returns
    ``""`` when nothing usable remains. Callers pass ``prefix="t"`` for tables
    and ``prefix="c"`` for columns.
    """
    cleaned = _NAME_SANITIZE_RE.sub("_", name).strip("_").lower()
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned


def escape_sql_string(value: str) -> str:
    """Escape backslash and single-quote for use inside a SQL string literal."""
    return value.replace("\\", "\\\\").replace("'", "''")


def render_sql_value(value: Any) -> str:
    """Render a value into its statement form.

    ``None`` becomes ``NULL``; everything else becomes a quoted, escaped string
    and relies on Delta casting the literal to the column type on insert.
    """
    if value is None:
        return "NULL"
    return f"'{escape_sql_string(str(value))}'"


def build_insert_statement(
    fq_table: str,
    col_names: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> str:
    """Build one ``INSERT OVERWRITE TABLE`` statement for the given rows.

    ``INSERT OVERWRITE`` is atomic, idempotent on re-run, and a single round
    trip, so it replaces a freshly created table's contents in one statement.
    """
    columns_clause = ", ".join(quote_identifier(c) for c in col_names)
    values_clauses = ["(" + ", ".join(render_sql_value(v) for v in row) + ")" for row in rows]
    return f"INSERT OVERWRITE TABLE {fq_table} ({columns_clause}) VALUES\n  " + ",\n  ".join(
        values_clauses
    )


def constraint_name(
    prefix: str, parts: Sequence[str], *, max_len: int = _CONSTRAINT_NAME_LIMIT
) -> str:
    """Build a deterministic, length-guarded constraint name.

    Joins ``prefix`` with the (already-sanitized) ``parts``. When the result
    exceeds ``max_len`` it keeps the readable prefix outside the truncated
    window and appends a stable 12-character SHA-1 suffix so distinct inputs
    stay distinct.
    """
    body = "__".join(p for p in parts if p)
    name = f"{prefix}_{body}" if body else prefix
    if len(name) <= max_len:
        return name
    # Disambiguation only, not security: same digest bytes, silences S324.
    digest = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    keep = max_len - len(prefix) - 1 - len(digest) - 1
    return f"{prefix}_{name[len(prefix) + 1 :][:keep]}_{digest}"


@dataclass
class MaterializedTable:
    """A table that was actually created, with the identifiers the FK pass needs.

    ``columns`` is the set of sanitized column names that landed in the table;
    ``foreign_keys`` is the source spec's raw FK list, deferred to the second
    pass. The shell builds this record from a :class:`TablePlan` only once its
    ``CREATE`` has actually run, so :func:`build_foreign_key_statements` is
    handed exactly the tables that exist.
    """

    safe_name: str
    columns: frozenset[str]
    foreign_keys: list[dict[str, Any]]


@dataclass
class TablePlan:
    """The statements to run for one table, plus what the shell needs to tally.

    ``create_sql`` always runs; ``insert_sql`` runs only when present (a table
    with sample rows). ``has_primary_key`` records whether the ``CREATE`` carries
    an inline ``PRIMARY KEY`` clause, so the shell can count
    ``pk_constraints_added`` once the create succeeds. ``record`` is the
    :class:`MaterializedTable` the foreign-key pass keys on, registered by the
    shell only after the create runs. ``*_label`` are human-readable tags for
    logging only.
    """

    create_sql: str
    create_label: str
    insert_sql: str | None
    insert_label: str | None
    has_primary_key: bool
    row_count: int
    record: MaterializedTable


@dataclass
class TableBuild:
    """The pure outcome of building one table's statements (no execution).

    ``plan`` is ``None`` when the table is skipped at build time (unusable name,
    no columns, or no coercible columns); ``stats`` then carries that skip in
    ``tables_skipped``. When ``plan`` is present, ``stats`` carries only the
    build-time counts known without running SQL (``type_fallbacks``); the shell
    adds the runtime counts as it executes the plan.
    """

    plan: TablePlan | None
    stats: MaterializeStats


def read_schema_entry(entry: dict[str, Any]) -> tuple[str, str]:
    """Return ``(uc_schema, source_id)`` for a blueprint schema entry.

    Raises ``ValueError`` naming the missing key(s) when ``uc_schema`` or
    ``source_id`` is absent or blank, so a malformed blueprint fails loudly at
    the boundary rather than emitting a half-formed schema.
    """
    missing = [k for k in ("uc_schema", "source_id") if not entry.get(k)]
    if missing:
        raise ValueError(f"blueprint schema entry missing required key(s) {missing}: {entry!r}")
    return entry["uc_schema"], entry["source_id"]


def build_create_schema_statement(
    catalog_q: str,
    uc_schema: str,
    source_id: str,
    *,
    property_prefix: str,
) -> tuple[str, str]:
    """Build the ``CREATE SCHEMA`` statement and its log label.

    ``property_prefix`` names the schema comment, mirroring the ``TBLPROPERTIES``
    prefix the tables carry.
    """
    schema_q = quote_identifier(uc_schema)
    sql = (
        f"CREATE SCHEMA IF NOT EXISTS {catalog_q}.{schema_q}"
        f" COMMENT '{property_prefix} source: {escape_sql_string(source_id)}'"
    )
    return sql, f"CREATE SCHEMA {uc_schema}"


def build_table(
    table: dict[str, Any],
    *,
    catalog_q: str,
    schema_q: str,
    source_id: str,
    property_prefix: str,
    type_map: Mapping[str, str] = DEFAULT_DELTA_TYPE_MAP,
) -> TableBuild:
    """Build one table's statements (with its primary key folded into the CREATE).

    The primary key is declared inline: its columns carry ``NOT NULL`` and the
    statement ends with an inline ``CONSTRAINT ... PRIMARY KEY (...)`` clause, so
    one ``CREATE`` replaces the former create / set-not-null / add-constraint
    sequence. A key is dropped (no clause emitted) when its columns did not all
    survive sanitization, or when a sample row carries a NULL in a PK column
    (which the inline ``NOT NULL`` would reject, failing the whole insert);
    dropping it keeps the rows. Foreign keys are deferred to
    :func:`build_foreign_key_statements`, since they reference tables that may
    not exist yet.

    Returns a :class:`TableBuild`. ``plan`` is ``None`` when the table is skipped
    at build time (unusable name, no columns, or no coercible columns), with the
    skip recorded in ``stats.tables_skipped``. ``property_prefix`` names the
    ``TBLPROPERTIES`` keys (``<prefix>.source_id`` and so on); ``type_map`` is the
    source-to-Delta type map.
    """
    raw_name = table.get("name", "")
    safe_name = sanitize_identifier(raw_name, prefix="t")
    if not safe_name:
        return TableBuild(None, MaterializeStats(tables_skipped=1))
    table_q = quote_identifier(safe_name)
    fq = f"{catalog_q}.{schema_q}.{table_q}"

    columns = table.get("columns") or []
    if not columns:
        return TableBuild(None, MaterializeStats(tables_skipped=1))

    type_fallbacks = 0
    typed_cols: list[tuple[str, str]] = []  # (safe column name, Delta type)
    safe_col_names: list[str] = []
    keep_col_mask: list[bool] = []
    for col in columns:
        safe_col = sanitize_identifier(col.get("name", ""), prefix="c")
        if not safe_col:
            keep_col_mask.append(False)
            continue
        raw_type = str(col.get("type", "")).strip()
        delta_type, fellback = coerce_type(raw_type, type_map)
        if fellback:
            type_fallbacks += 1
        typed_cols.append((safe_col, delta_type))
        safe_col_names.append(safe_col)
        keep_col_mask.append(True)

    if not typed_cols:
        return TableBuild(None, MaterializeStats(tables_skipped=1))

    safe_col_set = frozenset(safe_col_names)

    # Prepare the sample rows down to the surviving columns up front, so the
    # null-aware PK gate below and the INSERT both work from the same rows: each
    # kept row aligns positionally with safe_col_names.
    kept_rows = [
        tuple(v for v, keep in zip(row, keep_col_mask, strict=False) if keep)
        for row in (table.get("rows") or [])
    ]
    kept_rows = [r for r in kept_rows if len(r) == len(safe_col_names)]

    # Primary key, folded into the CREATE: a valid key declares its columns NOT
    # NULL and an inline CONSTRAINT clause in the one statement, so UC's
    # NOT-NULL-before-PK requirement is satisfied without a follow-up ALTER. An
    # invalid key, or one whose sample rows carry a NULL in a PK column (which
    # the inline NOT NULL would reject, failing the whole INSERT and dropping
    # every row), resolves to no columns, so no clause is emitted and the rows
    # are kept.
    pk_cols = _resolve_primary_key_columns(
        table.get("primary_keys") or [], safe_col_names, kept_rows
    )
    pk_col_set = frozenset(pk_cols)
    col_defs = [
        f"{quote_identifier(name)} {delta_type}" + (" NOT NULL" if name in pk_col_set else "")
        for name, delta_type in typed_cols
    ]
    if pk_cols:
        pk_name = constraint_name("pk", [safe_name])
        pk_cols_clause = ", ".join(quote_identifier(c) for c in pk_cols)
        col_defs.append(f"CONSTRAINT {quote_identifier(pk_name)} PRIMARY KEY ({pk_cols_clause})")

    fks_json = json.dumps(table.get("foreign_keys") or [])
    pks_json = json.dumps(table.get("primary_keys") or [])
    tbl_properties = (
        f"'{property_prefix}.source_id' = '{escape_sql_string(source_id)}',"
        f"'{property_prefix}.original_name' = '{escape_sql_string(raw_name)}',"
        f"'{property_prefix}.primary_keys' = '{escape_sql_string(pks_json)}',"
        f"'{property_prefix}.foreign_keys' = '{escape_sql_string(fks_json)}'"
    )
    create_sql = (
        f"CREATE TABLE IF NOT EXISTS {fq} (\n  "
        + ",\n  ".join(col_defs)
        + f"\n) USING DELTA TBLPROPERTIES ({tbl_properties})"
    )

    insert_sql = build_insert_statement(fq, safe_col_names, kept_rows) if kept_rows else None
    plan = TablePlan(
        create_sql=create_sql,
        create_label=f"CREATE TABLE {fq}",
        insert_sql=insert_sql,
        insert_label=f"INSERT OVERWRITE {fq}" if insert_sql is not None else None,
        has_primary_key=bool(pk_cols),
        row_count=len(kept_rows),
        record=MaterializedTable(
            safe_name=safe_name,
            columns=safe_col_set,
            foreign_keys=list(table.get("foreign_keys") or []),
        ),
    )
    return TableBuild(plan, MaterializeStats(type_fallbacks=type_fallbacks))


def _resolve_primary_key_columns(
    primary_keys: list[str],
    column_names: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[str]:
    """Return the sanitized PK columns to fold into the CREATE, or ``[]``.

    UC requires PK columns to be NOT NULL, which the inline CREATE declares
    alongside the constraint. The whole key is dropped (an empty list, so no
    inline clause is emitted) in two cases, since both would otherwise be wrong:

    - any PK column was dropped during sanitization or never landed as a real
      column, which would make the key partial; or
    - a prepared sample ``row`` carries a NULL in a PK column. The inline NOT
      NULL would reject that row and fail the whole ``INSERT OVERWRITE``, losing
      every row; dropping the key keeps the data (the table lands without its
      informational PK, matching the old add-PK-after-insert behavior).

    Pure: it decides which columns the caller declares, and runs no SQL.
    ``column_names`` is the surviving-column order that each ``rows`` tuple
    aligns to.
    """
    column_set = set(column_names)
    safe_pk_cols = [sanitize_identifier(c, prefix="c") for c in primary_keys]
    safe_pk_cols = [c for c in safe_pk_cols if c and c in column_set]
    if not safe_pk_cols or len(safe_pk_cols) != len(primary_keys):
        return []
    pk_indexes = [column_names.index(c) for c in safe_pk_cols]
    if any(row[i] is None for row in rows for i in pk_indexes):
        return []
    return safe_pk_cols


def build_foreign_key_statements(
    materialized: dict[str, MaterializedTable],
    *,
    catalog_q: str,
    schema_q: str,
) -> list[tuple[str, str]]:
    """Build the second-pass ``ALTER ... ADD CONSTRAINT ... FOREIGN KEY`` statements.

    Given the tables that were actually created (so a foreign key only points at
    a table that exists), returns ``(statement, label)`` pairs in materialized
    order. Skips any FK whose child or parent columns were dropped during
    sanitization, whose arity does not match, or whose target table/columns are
    not among ``materialized``. Running each statement (and tolerating a failure)
    is the shell's job.
    """
    statements: list[tuple[str, str]] = []
    for child in materialized.values():
        child_fq = f"{catalog_q}.{schema_q}.{quote_identifier(child.safe_name)}"
        for fk in child.foreign_keys:
            src_cols = [sanitize_identifier(c, prefix="c") for c in (fk.get("columns") or [])]
            ref_cols = [
                sanitize_identifier(c, prefix="c") for c in (fk.get("referred_columns") or [])
            ]
            parent_name = sanitize_identifier(fk.get("foreign_table", ""), prefix="t")

            if not parent_name or parent_name not in materialized:
                continue
            if not src_cols or len(src_cols) != len(ref_cols):
                continue
            if any(c not in child.columns for c in src_cols):
                continue
            parent = materialized[parent_name]
            if any(c not in parent.columns for c in ref_cols):
                continue

            fk_name = constraint_name("fk", [child.safe_name, *src_cols])
            parent_fq = f"{catalog_q}.{schema_q}.{quote_identifier(parent_name)}"
            src_clause = ", ".join(quote_identifier(c) for c in src_cols)
            ref_clause = ", ".join(quote_identifier(c) for c in ref_cols)
            statements.append(
                (
                    f"ALTER TABLE {child_fq} ADD CONSTRAINT {quote_identifier(fk_name)}"
                    f" FOREIGN KEY ({src_clause})"
                    f" REFERENCES {parent_fq} ({ref_clause})",
                    f"ADD FOREIGN KEY {child_fq} -> {parent_fq}",
                )
            )
    return statements
