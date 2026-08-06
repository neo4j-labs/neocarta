"""The shared hatch implementations.

They exist because more than one connector needs the same operation with different arguments.
Sharing keeps the gate metric honest — ``hatch_usage`` still counts one use per declaration site.
"""

import pytest

from neocarta.connectors.utils.generate_id import generate_column_id, generate_schema_id
from neocarta.errors import ConfigError
from neocarta.etl.metadata_normalizer import (
    ScopeContext,
    container_path_from,
    static_scope,
)


class TestContainerPathFrom:
    """Recover a natural key from a precomputed dotted id."""

    def test_it_assigns_segments_positionally(self):
        project = container_path_from("dataset_id", ("database_name", "schema_name"))
        assert project({"dataset_id": "proj.sales"}) == {
            "dataset_id": "proj.sales",
            "database_name": "proj",
            "schema_name": "sales",
        }

    def test_a_trailing_leaf_can_be_left_unassigned(self):
        """A ``column_id`` has four segments but a value row needs only its three container ones."""
        project = container_path_from(
            "column_id", ("database_name", "schema_name", "table_name"), id_segments=4
        )
        assigned = project({"column_id": "db.s.t.c"})
        assert assigned["table_name"] == "t"
        assert "column_name" not in assigned

    def test_a_none_field_skips_that_segment(self):
        """A frame that supplies a real name should bind that, not the id's spelling of it."""
        project = container_path_from("dataset_id", (None, "schema_name"))
        assigned = project({"dataset_id": "proj.sales", "project_id": "real-project-id"})
        assert assigned["schema_name"] == "sales"
        assert "database_name" not in assigned
        assert assigned["project_id"] == "real-project-id"

    def test_the_original_row_is_not_mutated(self):
        row = {"dataset_id": "proj.sales"}
        container_path_from("dataset_id", ("database_name", "schema_name"))(row)
        assert row == {"dataset_id": "proj.sales"}

    def test_a_dotted_database_name_is_not_a_separator(self):
        """A domain-scoped GCP project is ``example.com:my-project`` — dots and all.

        ``generate_id``'s ``_normalize`` maps ``-`` and space to ``_`` but leaves ``.`` and ``:``
        alone, so a left-to-right split counts the project's own dots as separators and rejects
        the row — aborting a whole connector on a source the hand-written transforms handle
        today. Only the trailing segment count is known, so the split runs right to left.
        """
        project = container_path_from(
            "column_id", ("database_name", "schema_name", "table_name"), id_segments=4
        )
        assigned = project(
            {"column_id": generate_column_id("example.com:my-project", "sales", "orders", "id")}
        )
        assert assigned["database_name"] == "example.com:my_project"
        assert assigned["schema_name"] == "sales"
        assert assigned["table_name"] == "orders"

    def test_a_dotted_database_name_survives_a_two_segment_id(self):
        project = container_path_from("dataset_id", (None, "schema_name"))
        assigned = project({"dataset_id": generate_schema_id("example.com:my-project", "sales")})
        assert assigned["schema_name"] == "sales"

    def test_a_truncated_id_raises_rather_than_binding_a_short_path(self):
        """Binding a truncated path would mint wrong ids, silently."""
        project = container_path_from("column_id", ("database_name", "schema_name", "table_name"))
        with pytest.raises(ConfigError, match="expected a 3-segment column_id"):
            project({"column_id": "db.s"})

    def test_extra_leading_dots_belong_to_the_first_segment(self):
        """The counterpart of splitting right to left, stated so it is a decision not an accident.

        Only the trailing segment count is known, so anything before it is the database name —
        dots included. That is what makes a domain-scoped project bind; the cost is that a dot in
        a *trailing* segment cannot be detected, which is why the guard only refuses truncation.
        """
        project = container_path_from("column_id", ("database_name", "schema_name", "table_name"))
        assert project({"column_id": "db.extra.s.t"})["database_name"] == "db.extra"

    def test_an_impossible_declaration_fails_at_build_time(self):
        """More fields than segments is a bug in the declaration, not in the data."""
        with pytest.raises(ConfigError, match="cannot be longer than the id"):
            container_path_from("dataset_id", ("a", "b", "c"), id_segments=2)


class TestStaticScope:
    """The most-shared property-scope semantics: a constant list per family."""

    def test_a_declared_family_gets_its_list(self):
        scope = static_scope({"column_nodes": ["name", "type"]})
        context = ScopeContext(family="column_nodes", nodes=[], source_columns=())
        assert scope(context) == ["name", "type"]

    def test_an_undeclared_family_falls_back_to_the_loader_default(self):
        """An empty list means "no allowlist", which is how BigQuery relies on the defaults."""
        scope = static_scope({"column_nodes": ["name"]})
        context = ScopeContext(family="table_nodes", nodes=[], source_columns=())
        assert scope(context) == []

    def test_the_returned_list_is_a_copy(self):
        """A caller mutating the result must not corrupt every later call."""
        declared = ["name", "type"]
        scope = static_scope({"column_nodes": declared})
        context = ScopeContext(family="column_nodes", nodes=[], source_columns=())
        scope(context).append("leaked")
        assert scope(context) == ["name", "type"]
        assert declared == ["name", "type"]
