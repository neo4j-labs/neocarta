"""The two central-transform rules the three proof connectors do not exercise.

Found by mutation-testing the mechanism: breaking the ``display_name`` label fallback, or making
a child edge ignore its parent's resolved id, left the whole parity suite green. Both rules are
real — the contract specifies them and Dataplex depends on them — but no connector in the proof
set supplies a ``display_name`` or an ``explicit_id``, so neither path was reached.

Driven from hand-built records rather than a connector fixture, deliberately: a fixture that
exercised these would have to be invented, and an invented fixture proves less than stating the
rule directly.
"""

from __future__ import annotations

import pytest

from neocarta.connectors.utils.generate_id import generate_table_id
from neocarta.etl.metadata_normalizer.normalized_schema import (
    BusinessTermRecord,
    CategoryRecord,
    ColumnRecord,
    DatabaseRecord,
    GlossaryRecord,
    SchemaRecord,
    TableRecord,
)
from tests.support.mapping_spike import BIGQUERY_SCHEMA, CSV, transformer_for

TABLE_KEY = {"database_name": "db", "schema_name": "s", "table_name": "orders"}


class TestDisplayNameIsTheLabelAndTheKeyStaysTheKey:
    """A source supplying a human label uses it as the node name, never as the identity segment.

    This is the Dataplex shape: identity is a slug while ``*_name`` columns hold the label. The
    contract keeps them apart (``normalized_schema/README.md``: *"Downstream label = display_name
    or table_name"*), and the transform has to honour that split — using ``display_name`` for the
    id would mint the wrong node, and ignoring it would show users a slug.
    """

    def test_a_table_display_name_becomes_the_name_not_the_id(self) -> None:
        record = TableRecord.model_validate({**TABLE_KEY, "display_name": "Customer Orders"})
        transformer = transformer_for(BIGQUERY_SCHEMA).transform({"tables": [record]})
        node = transformer.table_nodes[0]
        assert node.name == "Customer Orders"
        assert node.id == generate_table_id("db", "s", "orders")

    def test_a_table_without_a_display_name_falls_back_to_its_key(self) -> None:
        record = TableRecord.model_validate(TABLE_KEY)
        transformer = transformer_for(BIGQUERY_SCHEMA).transform({"tables": [record]})
        assert transformer.table_nodes[0].name == "orders"

    @pytest.mark.parametrize(
        ("table", "record", "row", "family", "key_name"),
        [
            (
                "glossaries",
                GlossaryRecord,
                {"glossary_name": "gloss", "display_name": "Business Glossary"},
                "glossary_nodes",
                "gloss",
            ),
            (
                "categories",
                CategoryRecord,
                {"glossary_name": "gloss", "category_name": "cat", "display_name": "A Category"},
                "category_nodes",
                "cat",
            ),
            (
                "business_terms",
                BusinessTermRecord,
                {
                    "glossary_name": "gloss",
                    "category_name": "cat",
                    "term_name": "term",
                    "display_name": "A Term",
                },
                "business_term_nodes",
                "term",
            ),
        ],
    )
    def test_every_glossary_record_with_a_label_uses_it(
        self, table: str, record: type, row: dict, family: str, key_name: str
    ) -> None:
        """All three glossary grains carry the identity/label split, so all three are checked."""
        transformer = transformer_for(CSV).transform({table: [record.model_validate(row)]})
        node = getattr(transformer, family)[0]
        assert node.name == row["display_name"]
        assert node.id.endswith(key_name)


class TestTransformIsRepeatable:
    """Calling ``transform()`` twice assigns rather than accumulates.

    Today's transformers overwrite their caches (``self._node_cache[...] = nodes``), so
    re-running one is a no-op. The mechanism appended, which silently doubled every family.
    That is reachable in normal use: a connector's ``transform()`` can be re-called after a
    failed ``load()``, and duplicated rows would go straight to the writer.
    """

    def test_a_second_transform_replaces_rather_than_appends(self) -> None:
        records = {
            "columns": [
                ColumnRecord.model_validate({**TABLE_KEY, "column_name": name})
                for name in ("a", "b")
            ]
        }
        transformer = transformer_for(BIGQUERY_SCHEMA)
        transformer.transform(records)
        first = [node.id for node in transformer.column_nodes]
        transformer.transform(records)
        assert [node.id for node in transformer.column_nodes] == first
        assert len(transformer.has_column_relationships) == len(records["columns"])

    def test_a_second_transform_with_different_records_drops_the_first(self) -> None:
        """State from an earlier run must not leak — including the resolved-id map."""
        transformer = transformer_for(BIGQUERY_SCHEMA)
        transformer.transform(
            {"tables": [TableRecord.model_validate({**TABLE_KEY, "explicit_id": "STALE"})]}
        )
        transformer.transform(
            {"columns": [ColumnRecord.model_validate({**TABLE_KEY, "column_name": "id"})]}
        )
        assert transformer.table_nodes == []
        # The stale override must not still be resolving this column's parent endpoint.
        assert transformer.has_column_relationships[0].table_id == generate_table_id(
            "db", "s", "orders"
        )


class TestAParentOverridePropagatesIntoChildEdges:
    """A child's edge points at its parent's *resolved* id, not a freshly generated one.

    ``explicit-id-override.md`` makes the **D6** override win for the row that declares it. If a
    containment edge regenerated its parent endpoint instead of reading what the parent resolved
    to, the child would point at a node that does not exist — a dangling edge the loader drops
    silently, because relationship endpoints are ``MATCH``ed rather than ``MERGE``d.

    Generation and lookup agree whenever no override is present, which is exactly why the three
    proof connectors could not detect the difference.
    """

    def test_a_schema_edge_uses_the_databases_overridden_id(self) -> None:
        records = {
            "databases": [
                DatabaseRecord.model_validate({"database_name": "db", "explicit_id": "OVERRIDE"})
            ],
            "schemas": [SchemaRecord.model_validate({"database_name": "db", "schema_name": "s"})],
        }
        transformer = transformer_for(BIGQUERY_SCHEMA).transform(records)
        assert transformer.database_nodes[0].id == "OVERRIDE"
        assert transformer.has_schema_relationships[0].database_id == "OVERRIDE"

    def test_a_column_edge_uses_the_tables_overridden_id(self) -> None:
        records = {
            "tables": [TableRecord.model_validate({**TABLE_KEY, "explicit_id": "TBL"})],
            "columns": [ColumnRecord.model_validate({**TABLE_KEY, "column_name": "id"})],
        }
        transformer = transformer_for(BIGQUERY_SCHEMA).transform(records)
        assert transformer.table_nodes[0].id == "TBL"
        assert transformer.has_column_relationships[0].table_id == "TBL"

    def test_a_child_of_an_unemitted_parent_still_generates(self) -> None:
        """The fallback half: a connector emitting only columns gets today's generated parent id.

        Several connectors do exactly this — a facet-only or column-only frame set — so the
        fallback is the common path, not an error case.
        """
        records = {"columns": [ColumnRecord.model_validate({**TABLE_KEY, "column_name": "id"})]}
        transformer = transformer_for(BIGQUERY_SCHEMA).transform(records)
        assert transformer.has_column_relationships[0].table_id == generate_table_id(
            "db", "s", "orders"
        )
