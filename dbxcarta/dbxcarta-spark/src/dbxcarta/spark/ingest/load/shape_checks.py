"""Derive PyDeequ data-quality checks from the carta-schema core models.

The shape every node and relationship DataFrame must satisfy is already
described by the Pydantic models in :mod:`carta_schema.rdbms.core`. Rather than
hand-maintain a parallel list of checks that can drift from the models, we read
the models' fields and derive the checks from them:

- a field whose annotation does not include ``None`` becomes a not-null
  (completeness) check,
- a ``bool`` field additionally becomes a Boolean type check,
- Optional fields and the embedding array are left unchecked.

:func:`derive_constraints` is pure and Spark-free, so the Pydantic-to-check
mapping is unit-tested without a JVM. :func:`add_model_checks` and
:func:`verify_shape` turn those constraints into a PyDeequ ``Check`` and run it
natively over a DataFrame; both import ``pydeequ`` lazily so this module loads
even where PyDeequ and its Deequ JAR are not installed.

Only the core labels are handled: Database, Schema, Table, Column and
HAS_SCHEMA, HAS_TABLE, HAS_COLUMN, REFERENCES. Value / HAS_VALUE live in the
expanded model and are out of scope.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from carta_schema.rdbms.core import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from dbxcarta.spark.contract import NodeLabel, RelType

if TYPE_CHECKING:
    from pydantic import BaseModel
    from pydeequ.checks import Check
    from pyspark.sql import DataFrame, SparkSession


class ShapeViolationError(RuntimeError):
    """Raised when a built DataFrame fails its derived shape checks."""


@dataclass(frozen=True)
class ShapeConstraint:
    """One derived check: ``kind`` applied to ``column``.

    ``kind`` is ``"complete"`` (the column must be non-null) or ``"boolean"``
    (the column must hold a real boolean).
    """

    kind: str
    column: str


# Core node labels -> their model. Value is out of scope (expanded model).
NODE_MODELS: dict[NodeLabel, type[BaseModel]] = {
    NodeLabel.DATABASE: Database,
    NodeLabel.SCHEMA: Schema,
    NodeLabel.TABLE: Table,
    NodeLabel.COLUMN: Column,
}

# Core relationship types -> (model, field-to-DataFrame-column map). The
# structural HAS_* DataFrames carry transient `source_id`/`target_id` join
# columns (see schema_graph.py), so each model's endpoint field names are
# remapped onto them. REFERENCES already emits `source_column_id` /
# `target_column_id`, which match its model, so its map is empty.
REL_MODELS: dict[RelType, tuple[type[BaseModel], dict[str, str]]] = {
    RelType.HAS_SCHEMA: (HasSchema, {"database_id": "source_id", "schema_id": "target_id"}),
    RelType.HAS_TABLE: (HasTable, {"schema_id": "source_id", "table_id": "target_id"}),
    RelType.HAS_COLUMN: (HasColumn, {"table_id": "source_id", "column_id": "target_id"}),
    RelType.REFERENCES: (References, {}),
}


def _is_optional(annotation: object) -> bool:
    """True when ``None`` is part of the type annotation (e.g. ``str | None``)."""
    return type(None) in typing.get_args(annotation)


def _base_type(annotation: object) -> object:
    """The meaningful type of a field annotation.

    For an Optional union (``X | None``) this is ``X``. For anything else,
    including generic containers like ``list[float]``, it is the annotation
    unchanged. Only unions are unwrapped: calling ``get_args`` on a container
    would wrongly return its element type (``get_args(list[float])`` is
    ``(float,)``).
    """
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return args[0] if args else annotation
    return annotation


def derive_constraints(
    model: type[BaseModel],
    field_to_col: dict[str, str] | None = None,
) -> list[ShapeConstraint]:
    """Read ``model.model_fields`` and return the checks its shape implies.

    A field whose annotation does not include ``None`` yields a ``"complete"``
    constraint; a ``bool`` field additionally yields a ``"boolean"`` one. List
    fields (the embedding) and Optional fields yield nothing. ``field_to_col``
    renames a model field onto the DataFrame column it lands in.
    """
    field_to_col = field_to_col or {}
    constraints: list[ShapeConstraint] = []
    for name, field in model.model_fields.items():
        column = field_to_col.get(name, name)
        annotation = field.annotation
        base = _base_type(annotation)
        # Skip array columns (the embedding); Deequ cannot constrain them.
        # `list[float]` is a generic alias, so normalise to its origin before
        # comparing: `list[float] is list` is False, `get_origin(list[float])`
        # is `list`.
        if (typing.get_origin(base) or base) is list:
            continue
        if not _is_optional(annotation):
            constraints.append(ShapeConstraint("complete", column))
        if base is bool:
            constraints.append(ShapeConstraint("boolean", column))
    return constraints


def resolve(label: NodeLabel | RelType) -> tuple[type[BaseModel], dict[str, str]]:
    """Return the model and field-to-column map for a core node or relationship."""
    if isinstance(label, NodeLabel):
        return NODE_MODELS[label], {}
    return REL_MODELS[label]


def add_model_checks(
    check: Check,
    model: type[BaseModel],
    field_to_col: dict[str, str] | None = None,
) -> Check:
    """Apply the model's derived constraints to a PyDeequ ``Check``."""
    from pydeequ.checks import ConstrainableDataTypes

    for constraint in derive_constraints(model, field_to_col):
        if constraint.kind == "complete":
            check = check.isComplete(constraint.column)
        elif constraint.kind == "boolean":
            check = check.hasDataType(constraint.column, ConstrainableDataTypes.Boolean)
    return check


def verify_shape(spark: SparkSession, df: DataFrame, label: NodeLabel | RelType) -> None:
    """Run the derived shape checks over ``df``; raise on any violation.

    Builds a single error-level PyDeequ suite from the model behind ``label`` and
    runs it natively over the DataFrame. On failure it raises
    :class:`ShapeViolationError` listing the failed constraints, so a malformed
    batch stops before it is written to Neo4j.
    """
    from pydeequ.checks import Check, CheckLevel
    from pydeequ.verification import VerificationResult, VerificationSuite

    model, field_to_col = resolve(label)
    check = add_model_checks(Check(spark, CheckLevel.Error, f"{label} shape"), model, field_to_col)
    result = VerificationSuite(spark).onData(df).addCheck(check).run()
    if result.status != "Success":
        rows = VerificationResult.checkResultsAsDataFrame(spark, result).collect()
        failed = [r["constraint"] for r in rows if r["constraint_status"] != "Success"]
        raise ShapeViolationError(f"{label} failed shape checks: {failed}")
