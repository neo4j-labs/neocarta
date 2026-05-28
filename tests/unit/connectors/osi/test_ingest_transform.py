"""Unit tests for the OSI ingest transformer."""

import json

import pytest

from neocarta.connectors.osi.ingest.transform import (
    PLACEHOLDER_DB,
    PLACEHOLDER_SCHEMA,
    OsiIngestTransformer,
)


def _run(spec: dict) -> OsiIngestTransformer:
    """Transform helper used across tests."""
    t = OsiIngestTransformer()
    t.transform(spec)
    return t


# ---------------------------------------------------------------------- #
# Top-level semantic model
# ---------------------------------------------------------------------- #


def test_semantic_model_carries_osi_version(minimal_spec):
    """Top-level spec.version flows onto each OsiSemanticModel node."""
    t = _run(minimal_spec)
    assert len(t.osi_semantic_model_nodes) == 1
    sm = t.osi_semantic_model_nodes[0]
    assert sm.name == "sales_model"
    assert sm.osi_version == "0.2.0"
    assert sm.description == "Test semantic model"


def test_semantic_model_level_ai_context_attaches_to_domain(minimal_spec):
    """ai_context on the semantic model produces an OsiAiContext + HAS_ASPECT (Domain)."""
    t = _run(minimal_spec)
    sm_id = t.osi_semantic_model_nodes[0].id
    domain_aspects = [r for r in t.has_aspect_rels if r.source_label == "Domain"]
    assert len(domain_aspects) == 1
    assert domain_aspects[0].source_id == sm_id


# ---------------------------------------------------------------------- #
# Dotted source variants
# ---------------------------------------------------------------------- #


def test_three_part_source_emits_database_schema_table(minimal_spec):
    """db.schema.table source yields Database + Schema + OsiTable plus HasSchema/HasTable/DomainHasTable."""
    t = _run(minimal_spec)

    assert {n.name for n in t.database_nodes} == {"warehouse"}
    assert {n.name for n in t.schema_nodes} == {"public"}
    table_names = {n.name for n in t.table_nodes}
    assert {"orders", "customers"}.issubset(table_names)

    # Structural edges
    assert len(t.has_schema_rels) >= 1
    assert len(t.has_table_rels) == 2
    assert len(t.domain_has_table_rels) == 2

    # Database is deduped across datasets that share it
    assert len(t.database_nodes) == 1


def test_two_part_source_uses_placeholder_db_no_database_node():
    """schema.table source: Schema created under placeholder db; no Database node, no HasSchema."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {"name": "t1", "source": "public.t1", "fields": []},
                ],
            }
        ]
    }
    t = _run(spec)

    assert t.database_nodes == []
    assert len(t.schema_nodes) == 1
    assert t.schema_nodes[0].name == "public"
    assert t.schema_nodes[0].id.startswith(PLACEHOLDER_DB + ".")
    assert t.has_schema_rels == []
    assert len(t.has_table_rels) == 1
    assert len(t.domain_has_table_rels) == 1


def test_one_part_source_no_database_no_schema():
    """Bare table source: only OsiTable + DomainHasTable; no Database/Schema/structural edges."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [{"name": "t1", "source": "customers", "fields": []}],
            }
        ]
    }
    t = _run(spec)

    assert t.database_nodes == []
    assert t.schema_nodes == []
    assert t.has_schema_rels == []
    assert t.has_table_rels == []
    assert len(t.table_nodes) == 1
    assert len(t.domain_has_table_rels) == 1


def test_table_id_uses_placeholders_when_components_missing():
    """OsiTable.id is fully qualified with placeholders when source omits structural parts."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [{"name": "t", "source": "customers", "fields": []}],
            }
        ]
    }
    t = _run(spec)
    table_id = t.table_nodes[0].id
    assert PLACEHOLDER_DB in table_id
    assert PLACEHOLDER_SCHEMA in table_id
    assert table_id.endswith("customers")


def test_osi_table_preserves_original_source_string(minimal_spec):
    """OsiTable.source carries the raw OSI source string for round-trip fidelity."""
    t = _run(minimal_spec)
    sources = {n.source for n in t.table_nodes}
    assert sources == {"warehouse.public.orders", "warehouse.public.customers"}


# ---------------------------------------------------------------------- #
# Query source routing
# ---------------------------------------------------------------------- #


def test_query_source_produces_query_node_not_osi_table(query_source_spec):
    """SQL-query source materializes a Query node + HasQuery; no OsiTable / Database / Schema."""
    t = _run(query_source_spec)

    assert t.table_nodes == []
    assert t.database_nodes == []
    assert t.schema_nodes == []
    assert len(t.query_nodes) == 1
    assert t.query_nodes[0].name == "active_customers"
    assert t.query_nodes[0].content.startswith("SELECT")
    assert len(t.has_query_rels) == 1
    assert t.domain_has_table_rels == []


def test_query_source_fields_use_query_has_column(query_source_spec):
    """For query datasets, columns attach via QueryHasColumn (rel type still :HAS_COLUMN)."""
    t = _run(query_source_spec)
    assert len(t.column_nodes) == 1
    assert t.has_column_rels == []
    assert len(t.query_has_column_rels) == 1
    assert t.query_has_column_rels[0].query_id == t.query_nodes[0].id


# ---------------------------------------------------------------------- #
# Columns: PK / FK / time dimension
# ---------------------------------------------------------------------- #


def test_primary_key_columns_marked_is_primary_key(minimal_spec):
    """Columns whose names appear in dataset.primary_key get is_primary_key=True."""
    t = _run(minimal_spec)
    by_id = {c.id: c for c in t.column_nodes}
    order_id = next(c for c in t.column_nodes if c.name == "order_id" and "orders" in c.id)
    assert order_id.is_primary_key is True

    # Non-PK column in same table
    order_date = next(c for c in t.column_nodes if c.name == "order_date" and "orders" in c.id)
    assert order_date.is_primary_key is False


def test_foreign_key_columns_marked_from_relationships(minimal_spec):
    """Columns appearing in relationship.from_columns get is_foreign_key=True."""
    t = _run(minimal_spec)
    orders_customer_id = next(
        c for c in t.column_nodes if c.name == "customer_id" and "orders" in c.id
    )
    customers_customer_id = next(
        c for c in t.column_nodes if c.name == "customer_id" and "customers" in c.id
    )
    assert orders_customer_id.is_foreign_key is True
    # target-side columns are NOT FKs
    assert customers_customer_id.is_foreign_key is False


def test_time_dimension_field_marked():
    """field.dimension.is_time=True surfaces as OsiColumn.is_time_dimension=True."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t",
                        "source": "db.s.t",
                        "fields": [
                            {"name": "ts", "dimension": {"is_time": True}},
                            {"name": "other", "dimension": {"is_time": False}},
                            {"name": "plain"},
                        ],
                    }
                ],
            }
        ]
    }
    t = _run(spec)
    by_name = {c.name: c for c in t.column_nodes}
    assert by_name["ts"].is_time_dimension is True
    assert by_name["other"].is_time_dimension is False
    assert by_name["plain"].is_time_dimension is False


def test_osi_column_label_passthrough(minimal_spec):
    """OSI field.label is preserved on OsiColumn.label."""
    t = _run(minimal_spec)
    order_date = next(c for c in t.column_nodes if c.name == "order_date")
    assert order_date.label == "filter"


def test_unique_keys_preserved_and_empty_filtered():
    """unique_keys passes through; entries that are empty lists are dropped."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t",
                        "source": "db.s.t",
                        "primary_key": ["id"],
                        "unique_keys": [["a"], [], ["b", "c"]],
                        "fields": [],
                    }
                ],
            }
        ]
    }
    t = _run(spec)
    assert t.table_nodes[0].unique_keys == [["a"], ["b", "c"]]


# ---------------------------------------------------------------------- #
# Expressions
# ---------------------------------------------------------------------- #


def test_field_expressions_create_expression_nodes_with_has_expression(minimal_spec):
    """Each dialect entry produces an Expression node + HAS_EXPRESSION from the column."""
    t = _run(minimal_spec)
    # 4 columns have expressions (3 in orders, 1 in customers)
    assert len(t.expression_nodes) >= 4
    column_expr_rels = [r for r in t.has_expression_rels if r.source_label == "Column"]
    assert len(column_expr_rels) >= 4


def test_metric_expression_links_back_to_metric(minimal_spec):
    """Metric expressions are owned by the Metric, not a column."""
    t = _run(minimal_spec)
    metric_expr_rels = [r for r in t.has_expression_rels if r.source_label == "Metric"]
    assert len(metric_expr_rels) == 1
    assert metric_expr_rels[0].source_id == t.metric_nodes[0].id


def test_identical_expressions_dedupe_within_owner():
    """Two identical (dialect, expression) entries on the same owner collapse to one Expression node."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t",
                        "source": "db.s.t",
                        "fields": [
                            {
                                "name": "c1",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "id"},
                                        {"dialect": "ANSI_SQL", "expression": "id"},
                                    ]
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    t = _run(spec)
    assert len(t.expression_nodes) == 1


# ---------------------------------------------------------------------- #
# ai_context handling and synonym → BusinessTerm tagging
# ---------------------------------------------------------------------- #


def test_ai_context_dict_with_synonyms_creates_business_terms(minimal_spec):
    """A dict ai_context with synonyms array creates BusinessTerm nodes + TAGGED_WITH edges."""
    t = _run(minimal_spec)
    bt_names = {bt.name for bt in t.business_term_nodes}
    # synonyms from orders ai_context + revenue from metric ai_context
    assert {"sales", "transactions", "revenue"}.issubset(bt_names)

    # Orders table should be tagged with both 'sales' and 'transactions'
    orders_id = next(c.id for c in t.table_nodes if c.name == "orders")
    orders_tags = [r for r in t.tagged_with_rels if r.source_id == orders_id]
    tagged_names = set()
    bt_by_id = {bt.id: bt.name for bt in t.business_term_nodes}
    for tw in orders_tags:
        tagged_names.add(bt_by_id[tw.business_term_id])
    assert {"sales", "transactions"}.issubset(tagged_names)


def test_ai_context_plain_string_creates_aspect_without_synonyms():
    """An ai_context that is a non-JSON string creates an Aspect but no BTs."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "ai_context": "free-form text instructions",
                "datasets": [],
            }
        ]
    }
    t = _run(spec)
    assert len(t.ai_context_nodes) == 1
    assert t.business_term_nodes == []
    assert t.tagged_with_rels == []


def test_ai_context_json_string_with_synonyms_parsed():
    """JSON-encoded string ai_context is parsed; synonyms inside become BusinessTerms."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t",
                        "source": "db.s.t",
                        "ai_context": json.dumps({"synonyms": ["alpha"]}),
                        "fields": [],
                    }
                ],
            }
        ]
    }
    t = _run(spec)
    assert {bt.name for bt in t.business_term_nodes} == {"alpha"}


def test_same_ai_context_payload_dedupes_aspect_within_semantic_model():
    """Identical ai_context content on two entities collapses to one Aspect node."""
    payload = {"synonyms": ["x"]}
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t1",
                        "source": "db.s.t1",
                        "ai_context": payload,
                        "fields": [],
                    },
                    {
                        "name": "t2",
                        "source": "db.s.t2",
                        "ai_context": payload,
                        "fields": [],
                    },
                ],
            }
        ]
    }
    t = _run(spec)
    assert len(t.ai_context_nodes) == 1
    # Two HAS_ASPECT rels (one per table) pointing at the same Aspect id
    table_aspects = [r for r in t.has_aspect_rels if r.source_label == "Table"]
    assert len(table_aspects) == 2
    assert {r.aspect_id for r in table_aspects} == {t.ai_context_nodes[0].id}


def test_synonyms_dedupe_business_term_within_ingest():
    """Synonyms repeating across entities produce a single BT node (deduped by derived id)."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t1",
                        "source": "db.s.t1",
                        "ai_context": {"synonyms": ["shared"]},
                        "fields": [],
                    },
                    {
                        "name": "t2",
                        "source": "db.s.t2",
                        "ai_context": {"synonyms": ["shared"]},
                        "fields": [],
                    },
                ],
            }
        ]
    }
    t = _run(spec)
    assert len(t.business_term_nodes) == 1
    assert t.business_term_nodes[0].name == "shared"
    # But two TAGGED_WITH rels (one per table)
    assert len(t.tagged_with_rels) == 2


# ---------------------------------------------------------------------- #
# Custom extensions
# ---------------------------------------------------------------------- #


def test_custom_extensions_create_aspect_with_vendor_name():
    """custom_extensions emit OsiCustomExtensions nodes carrying vendor + data."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {
                        "name": "t",
                        "source": "db.s.t",
                        "custom_extensions": [
                            {"vendor_name": "SNOWFLAKE", "data": '{"warehouse": "S"}'},
                            {"vendor_name": "DBT", "data": '{"materialization": "table"}'},
                        ],
                        "fields": [],
                    }
                ],
            }
        ]
    }
    t = _run(spec)
    assert len(t.custom_extension_nodes) == 2
    vendors = {n.vendor_name for n in t.custom_extension_nodes}
    assert vendors == {"SNOWFLAKE", "DBT"}


# ---------------------------------------------------------------------- #
# Relationships (Joins) and References
# ---------------------------------------------------------------------- #


def test_relationship_creates_join_with_source_target_and_used_in_join(minimal_spec):
    """A relationship produces a Join + HAS_SOURCE_TABLE + HAS_TARGET_TABLE + USED_IN_JOIN per column."""
    t = _run(minimal_spec)
    assert len(t.join_nodes) == 1
    assert t.join_nodes[0].name == "orders_to_customers"
    assert len(t.has_source_table_rels) == 1
    assert len(t.has_target_table_rels) == 1
    # One column on each side
    assert len(t.used_in_join_rels) == 2


def test_relationship_emits_paired_references(minimal_spec):
    """Each paired from/to column pair produces a References edge."""
    t = _run(minimal_spec)
    assert len(t.references_rels) == 1
    ref = t.references_rels[0]
    assert "orders" in ref.source_column_id
    assert "customers" in ref.target_column_id


def test_relationship_with_mismatched_column_counts_raises():
    """OSI spec requires equal from/to column counts; strict=True surfaces malformed input."""
    spec = {
        "semantic_model": [
            {
                "name": "m",
                "datasets": [
                    {"name": "a", "source": "db.s.a", "fields": [{"name": "x"}]},
                    {"name": "b", "source": "db.s.b", "fields": [{"name": "y"}, {"name": "z"}]},
                ],
                "relationships": [
                    {
                        "name": "bad",
                        "from": "a",
                        "to": "b",
                        "from_columns": ["x"],
                        "to_columns": ["y", "z"],
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValueError):
        _run(spec)


# ---------------------------------------------------------------------- #
# Full TPCDS fixture
# ---------------------------------------------------------------------- #


def test_tpcds_sample_transforms_without_errors(tpcds_spec):
    """The published TPC-DS OSI sample transforms cleanly into reasonable counts."""
    t = _run(tpcds_spec)

    # Top-level
    assert len(t.osi_semantic_model_nodes) == 1
    assert t.osi_semantic_model_nodes[0].name == "tpcds_retail_model"
    assert t.osi_semantic_model_nodes[0].osi_version == "0.2.0.dev0"

    # Datasets / structure
    assert len(t.table_nodes) > 0
    assert len(t.column_nodes) > 0
    assert len(t.has_column_rels) == len(t.column_nodes)
    assert len(t.domain_has_table_rels) == len(t.table_nodes)

    # All TPC-DS sources are `tpcds.public.<table>` — one Database, one Schema
    assert {n.name for n in t.database_nodes} == {"tpcds"}
    assert {n.name for n in t.schema_nodes} == {"public"}

    # Aspects: every entity that has an ai_context produces an Aspect; synonyms produce BTs
    assert len(t.ai_context_nodes) > 0
    assert len(t.business_term_nodes) > 0

    # Joins
    assert len(t.join_nodes) > 0
    assert len(t.has_source_table_rels) == len(t.join_nodes)
    assert len(t.has_target_table_rels) == len(t.join_nodes)
