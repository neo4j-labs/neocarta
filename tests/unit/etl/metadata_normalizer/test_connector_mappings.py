"""Every connector's declaration, swept for the mistakes a declaration can silently make.

A declaration is data, so most of its failure modes are typos that bind nothing rather than
exceptions that stop a run. What is tested here is only the part the goldens cannot see: whether a
declared source name is real, whether a hatch's *content* is right, and the per-connector
behaviours that a golden records but does not explain.
"""

from types import SimpleNamespace

import pytest

from neocarta.connectors.utils.generate_id import generate_database_id
from neocarta.etl.metadata_normalizer import (
    ScopeContext,
    bind,
    hatch_usage,
    normalize,
)
from tests.support.connectors.offline import OFFLINE_EXTRACTORS, build_extractor
from tests.support.connectors.registry import BY_CONNECTOR, DECLARATIONS


class TestTheSweepIsComplete:
    """Guard the guard: nothing may quietly drop out of the parametrization."""

    def test_every_declaration_has_an_offline_driver(self):
        missing = {declared.connector for declared in DECLARATIONS} - set(OFFLINE_EXTRACTORS)
        assert not missing, f"declared connectors with no offline driver: {sorted(missing)}"

    def test_the_declared_set_is_pinned(self):
        """Pinned exactly, so adding a connector forces a decision rather than drifting in.

        These five are the connectors an acceptance criterion or the design record asks for:
        ``bigquery/schema`` / ``jdbc/schema`` / ``csv`` carry the S1.6 goldens AC-1 is measured
        against, ``databricks/tags`` closes the governance gap ``mapping-mechanism.md`` §8.7 names
        for this ticket, and ``query_log`` is the only source that *fabricates* its rows, so it is
        the only one exercising the projection hatches at depth. Every other tabular connector
        flips in S4, against its own real fixtures.
        """
        assert {declared.connector for declared in DECLARATIONS} == {
            "bigquery/schema",
            "jdbc/schema",
            "csv",
            "databricks/tags",
            "query_log",
        }


class TestDeclaredSourcesResolve:
    """Every source a declaration names must exist on the connector's real extractor class.

    Checked against the **class**, not an instance, so a declaration cannot come to depend on an
    attribute that one particular extract happened to set. The hazard is real:
    ``UnityCatalogSchemaExtractor`` exposes ``catalog_info`` where every other schema extractor
    exposes ``database_info``, so a declaration assuming the convention fails deep inside
    ``getattr`` rather than at the declaration.
    """

    def test_every_source_is_a_class_accessor(self, connector):
        declared = BY_CONNECTOR[connector]
        missing = [
            source
            for table in declared.mapping.tables.values()
            for source in table.sources
            if not hasattr(declared.extractor_class, source)
        ]
        assert not missing, f"{connector} declares non-class accessors: {missing}"


class TestEveryConnectorProducesRecords:
    """A declaration that binds nothing is indistinguishable from a broken one."""

    def test_normalizing_yields_at_least_one_record(self, connector):
        output = normalize(build_extractor(connector), BY_CONNECTOR[connector].mapping)
        assert sum(len(rows) for rows in output.records.values()) > 0


class TestGovernanceFacetIsCovered:
    """The one coverage gap ``mapping-mechanism.md`` §8.7 named for this ticket.

    The S1.6 prototype consumed 10 of the contract's 13 tables, leaving the governance facet
    unconsumed and ``databricks/tags`` at 0 of its 3 families. Both governance records bind with
    zero renames and zero hatches, so the gap was in what the prototype reached for, not in the
    contract. The third family, ``HAS_VALUE_OPTION``, is derivable and correctly not a table.
    """

    def test_both_governance_tables_are_declared(self):
        assert set(BY_CONNECTOR["databricks/tags"].mapping.tables) == {
            "governance_tag_keys",
            "governance_tag_values",
        }

    def test_tag_namespace_and_value_resolve_from_the_source_vocabulary(self):
        output = normalize(
            build_extractor("databricks/tags"), BY_CONNECTOR["databricks/tags"].mapping
        )
        keys = output.records["governance_tag_keys"]
        values = output.records["governance_tag_values"]
        assert {record.tag_key for record in keys} == {"department", "cost_center", "free_form"}
        assert all(record.tag_namespace for record in keys)
        assert {record.tag_value for record in values} == {
            "finance",
            "hr",
            "sales",
            "alpha",
            "beta",
        }

    def test_a_system_tag_is_excluded_by_the_extractor_not_the_declaration(self):
        """The system-prefix filter is a caller-facing ingest option, so it stays in extract."""
        output = normalize(
            build_extractor("databricks/tags"), BY_CONNECTOR["databricks/tags"].mapping
        )
        assert not [
            record
            for record in output.records["governance_tag_keys"]
            if record.tag_key.startswith("system.")
        ]


class TestHatchesDoTheirJob:
    """The two hatches whose *content* nothing else exercises.

    A hatch that is only counted is not tested: ``hatch_usage`` sees ``row_filter is not None`` and
    ``property_scope is not None``, so deleting either fails the gate metric — but relaxing a
    predicate to ``lambda _: True``, or misspelling a family key so a scope silently returns
    ``[]``, does not. Both are D10-relevant, so both are pinned here.
    """

    def test_bigquery_drops_a_non_foreign_key_constraint_row(self):
        """The constraint frame is mixed: the extractor's query does not filter by type.

        A ``PRIMARY KEY`` row that survived would bind as a ``ForeignKeyRecord`` whose target comes
        from the self-join — a fabricated edge from a table to itself. The offline fixture contains
        only FK rows, so nothing else ever feeds the predicate a row it must reject.
        """
        table = BY_CONNECTOR["bigquery/schema"].mapping.tables["foreign_keys"]
        rows = [
            {
                "constraint_type": "PRIMARY KEY",
                "constraint_catalog": "p",
                "constraint_schema": "d",
                "table_name": "orders",
                "column_name": "id",
                "referenced_table": "orders",
                "referenced_column": "id",
            },
            {
                "constraint_type": "FOREIGN KEY",
                "constraint_catalog": "p",
                "constraint_schema": "d",
                "table_name": "order_items",
                "column_name": "order_id",
                "referenced_table": "orders",
                "referenced_column": "id",
            },
        ]
        kept = bind(rows, table.record, project=table.project, row_filter=table.row_filter)
        assert [record.source_table_name for record in kept] == ["order_items"]

    @pytest.mark.parametrize(
        ("scoped", "expected"),
        [
            (
                "databricks/tags",
                {
                    "governance_tag_key_nodes": ["name", "description"],
                    "governance_tag_value_nodes": ["name"],
                },
            ),
            (
                "query_log",
                {
                    "database_nodes": ["name", "service", "platform"],
                    "schema_nodes": ["name"],
                    "table_nodes": ["name"],
                    "column_nodes": ["name"],
                },
            ),
        ],
    )
    def test_static_property_scopes_match_their_connectors_load_calls(self, scoped, expected):
        """The scope *content* is hand-ported data, so it is pinned rather than merely counted.

        Each list is the ``properties_list=[...]`` argument at that connector's ``load_*()`` call
        sites. Misspell a family key and the hatch returns ``[]`` for it, which every layer
        downstream reads as "fall back to the loader's defaults" — for ``databricks/tags`` that
        means writing ``description = null`` onto tag values and erasing another source's, the
        exact **D10** clobber the scope exists to prevent.
        """
        scope = BY_CONNECTOR[scoped].mapping.property_scope
        for family, properties in expected.items():
            assert scope(ScopeContext(family, nodes=[], source_columns=())) == properties, family

    def test_a_family_outside_the_static_scope_falls_back(self):
        """The control: an undeclared family really does mean "loader defaults"."""
        scope = BY_CONNECTOR["databricks/tags"].mapping.property_scope
        assert scope(ScopeContext("database_nodes", nodes=[], source_columns=())) == []

    def test_jdbc_omits_key_flags_when_no_column_declares_one(self):
        """Truthiness, not ``is not None`` — and the difference is the whole point of the hatch.

        A view-only or keyless schema yields every ``is_primary_key`` / ``is_foreign_key`` as
        ``False``. Reducing with ``is not None`` would call that "the source defined them" and
        write ``is_primary_key: false`` onto every Column — the exact **D10** clobber
        ``_omit_unset_properties`` exists to prevent. The committed SchemaCrawler catalog always
        has at least one ``True``, so nothing else in the suite separates the two semantics.
        """
        scope = BY_CONNECTOR["jdbc/schema"].mapping.property_scope
        keyless = [
            SimpleNamespace(description=None, is_primary_key=False, is_foreign_key=False),
            SimpleNamespace(description=None, is_primary_key=False, is_foreign_key=False),
        ]
        assert scope(ScopeContext("column_nodes", keyless, ())) == ["name", "type", "nullable"]

        # Each flag is reduced independently, so a schema with primary keys but no foreign keys
        # writes `is_primary_key` and still says nothing about `is_foreign_key`.
        keyed = [SimpleNamespace(description=None, is_primary_key=True, is_foreign_key=False)]
        assert scope(ScopeContext("column_nodes", keyed, ())) == [
            "name",
            "type",
            "nullable",
            "is_primary_key",
        ]

    def test_an_unscoped_family_falls_back_to_the_loader_default(self):
        """The fallback arm of both bespoke scopes — unverified until now.

        ``serialize_transform`` records ``_properties`` only for families with a *non-empty*
        allowlist, so the parity suite compares 8 of CSV's 17 families and 2 of JDBC's 8; making
        either fallback return a non-empty list was invisible.
        """
        jdbc = BY_CONNECTOR["jdbc/schema"].mapping.property_scope
        csv = BY_CONNECTOR["csv"].mapping.property_scope
        assert jdbc(ScopeContext("table_nodes", [], ())) == []
        assert csv(ScopeContext("has_column_relationships", [], ("a",))) == []

    def test_the_governance_records_need_no_pre_fold(self):
        assert hatch_usage(BY_CONNECTOR["databricks/tags"].mapping) == {"property_scope": 1}


class TestQueryLogProjections:
    """The traps the field vocabulary cannot save the one row-fabricating connector from.

    The first two are pinned by ``tests/unit/etl/transform/test_query_log_passthrough_parity.py``
    as raw facts about the frames; here they are facts about the *declaration* that answers them.
    """

    @pytest.fixture
    def records(self):
        return normalize(build_extractor("query_log"), BY_CONNECTOR["query_log"].mapping)

    def test_the_schema_name_is_a_name_not_a_generated_id(self, records):
        """``dataset_id`` is a ratified ``schema_name`` synonym, but here it is an id."""
        for record in records.records["schemas"]:
            assert "." not in record.schema_name

    def test_the_column_table_name_is_the_table_not_the_sql_alias(self, records):
        """``column_info.table_name`` is the query's alias (``o``, ``c``)."""
        real_tables = {record.table_name for record in records.records["tables"]}
        assert {record.table_name for record in records.records["columns"]} <= real_tables

    def test_both_foreign_key_endpoints_carry_a_full_path(self, records):
        for record in records.records["foreign_keys"]:
            assert record.source_column_name
            assert record.target_column_name

    def test_a_path_recovered_from_an_id_carries_the_normalized_spelling(self, records):
        """A deliberate consequence of recovering a key path from a generated id.

        ``container_path_from`` splits an ``*_id`` whose segments ``generate_id`` already
        ``_normalize``d, so a record whose path comes from an id spells its container differently
        from a sibling that read the source column. Identity is unaffected — both spellings
        generate one id, which is why the S1.6 goldens were ratified with the same split on their
        ``values`` rows — but the records are not joinable on the *raw* natural key. Pinned so it
        is a known divergence rather than a discovery; the fix is for the extractor to keep the
        path it already had, which is an ``extract.py`` change and therefore S4.
        """
        assert {r.database_name for r in records.records["databases"]} == {"example-project-id"}
        assert {r.database_name for r in records.records["columns"]} == {"example_project_id"}
        assert generate_database_id("example-project-id") == generate_database_id(
            "example_project_id"
        )
