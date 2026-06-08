"""Derivation of PyDeequ shape checks from the carta-schema core models.

The mapping is the heart of Phase 2: a non-Optional field becomes a not-null
(completeness) check, a boolean field also becomes a Boolean type check, and
Optional fields plus the embedding array yield nothing. These tests pin that
mapping per model with no Spark or PyDeequ. The apply layer is checked against a
fake Check that records calls, and the live ``verify_shape`` run is gated on
PyDeequ being importable so it runs on Databricks/CI and skips elsewhere.
"""

from __future__ import annotations

import sys
import types

import pytest
from carta_schema.rdbms.core import Column, Database, Schema, Table
from dbxcarta.spark.contract import NodeLabel, RelType
from dbxcarta.spark.ingest.load.shape_checks import (
    ShapeConstraint,
    add_model_checks,
    derive_constraints,
    resolve,
)


def _pairs(constraints: list[ShapeConstraint]) -> list[tuple[str, str]]:
    return [(c.kind, c.column) for c in constraints]


def test_node_models_derive_id_and_name_completeness():
    for model in (Database, Schema, Table):
        assert _pairs(derive_constraints(model)) == [
            ("complete", "id"),
            ("complete", "name"),
        ]


def test_column_derives_completeness_plus_boolean_types():
    assert _pairs(derive_constraints(Column)) == [
        ("complete", "id"),
        ("complete", "name"),
        ("complete", "nullable"),
        ("boolean", "nullable"),
        ("complete", "is_primary_key"),
        ("boolean", "is_primary_key"),
        ("complete", "is_foreign_key"),
        ("boolean", "is_foreign_key"),
    ]


def test_optional_and_embedding_fields_yield_no_checks():
    # description, type (Optional) and embedding (list) are absent from Column's
    # derived constraints.
    checked = {c.column for c in derive_constraints(Column)}
    assert checked.isdisjoint({"description", "type", "embedding"})


def test_required_list_field_is_skipped_not_completeness_checked():
    # A required `list[float]` is still an array Deequ cannot constrain, so it
    # must be skipped rather than getting a (wrong) completeness check. Guards
    # the get_origin normalisation against generic aliases.
    from pydantic import BaseModel

    class _HasVector(BaseModel):
        id: str
        vector: list[float]

    assert _pairs(derive_constraints(_HasVector)) == [("complete", "id")]


def test_references_checks_both_endpoints_and_skips_optional_criteria():
    model, field_to_col = resolve(RelType.REFERENCES)
    assert _pairs(derive_constraints(model, field_to_col)) == [
        ("complete", "source_column_id"),
        ("complete", "target_column_id"),
    ]


@pytest.mark.parametrize(
    "rel_type",
    [RelType.HAS_SCHEMA, RelType.HAS_TABLE, RelType.HAS_COLUMN],
)
def test_structural_rels_remap_endpoints_onto_transient_join_columns(rel_type):
    # The HAS_* DataFrames carry source_id/target_id, not the model's *_id field
    # names, so the derived checks must land on the transient columns.
    model, field_to_col = resolve(rel_type)
    assert _pairs(derive_constraints(model, field_to_col)) == [
        ("complete", "source_id"),
        ("complete", "target_id"),
    ]


def test_resolve_covers_every_core_label():
    for label in (NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN):
        model, field_to_col = resolve(label)
        assert field_to_col == {}
        assert derive_constraints(model, field_to_col)


class _FakeCheck:
    """Records the PyDeequ Check calls add_model_checks would make."""

    def __init__(self):
        self.calls: list[tuple] = []

    def isComplete(self, column):
        self.calls.append(("isComplete", column))
        return self

    def hasDataType(self, column, datatype):
        self.calls.append(("hasDataType", column, datatype))
        return self


def test_add_model_checks_maps_constraints_to_check_calls(monkeypatch):
    # Stand in a fake pydeequ.checks so the lazy import resolves without the real
    # package or a JVM, then assert each derived constraint becomes the right
    # Check call in order.
    boolean_marker = object()
    fake_checks = types.ModuleType("pydeequ.checks")
    fake_checks.ConstrainableDataTypes = types.SimpleNamespace(Boolean=boolean_marker)
    monkeypatch.setitem(sys.modules, "pydeequ", types.ModuleType("pydeequ"))
    monkeypatch.setitem(sys.modules, "pydeequ.checks", fake_checks)

    recorder = _FakeCheck()
    add_model_checks(recorder, Column)

    assert recorder.calls == [
        ("isComplete", "id"),
        ("isComplete", "name"),
        ("isComplete", "nullable"),
        ("hasDataType", "nullable", boolean_marker),
        ("isComplete", "is_primary_key"),
        ("hasDataType", "is_primary_key", boolean_marker),
        ("isComplete", "is_foreign_key"),
        ("hasDataType", "is_foreign_key", boolean_marker),
    ]


def test_verify_shape_passes_and_fails_on_a_real_deequ_run(local_spark):
    # Live end-to-end check. Requires PyDeequ and a Deequ JAR matching the Spark
    # version, so it skips wherever that stack is absent (the gating prerequisite
    # in pydeeque.md). On Databricks/CI it proves a clean batch passes and a
    # null-id batch raises ShapeViolation before any write.
    pytest.importorskip("pydeequ")
    from dbxcarta.spark.ingest.load.shape_checks import ShapeViolationError, verify_shape

    good = local_spark.createDataFrame([("c1", "name")], ["id", "name"])
    verify_shape(local_spark, good, NodeLabel.SCHEMA)

    bad = local_spark.createDataFrame([(None, "name")], "id string, name string")
    with pytest.raises(ShapeViolationError):
        verify_shape(local_spark, bad, NodeLabel.SCHEMA)
