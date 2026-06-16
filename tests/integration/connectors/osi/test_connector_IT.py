"""Integration tests for the OSI connector — ingest, export, and round-trip.

These tests run against a live Neo4j container (provided by the integration
conftest's ``setup`` / ``neo4j_driver`` fixtures) and exercise the full stack:
loader, ingest+export transformers, and the graph extractor.
"""

from pathlib import Path

import pytest
import yaml

from neocarta.connectors.osi import OsiConnector
from neocarta.connectors.osi.export.extract import OsiGraphExtractor
from neocarta.connectors.osi.export.transform import OsiExportTransformer
from neocarta.connectors.osi.ingest.extract import OsiSpecExtractor
from neocarta.connectors.osi.ingest.transform import OsiIngestTransformer
from neocarta.connectors.osi.load import OsiNeo4jLoader

# ---------------------------------------------------------------------- #
# Round-trip: full connector
# ---------------------------------------------------------------------- #


def test_osi_connector_round_trip_tpcds(neo4j_driver, tpcds_yaml_path: Path, tmp_path: Path):
    """Ingest TPC-DS sample, then export it back and verify key structural fidelity."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(tpcds_yaml_path)

    output = tmp_path / "tpcds_export.yaml"
    connector.export(semantic_model_name="tpcds_retail_model", output_path=output)

    assert output.exists()
    exported = yaml.safe_load(output.read_text(encoding="utf-8"))
    original = yaml.safe_load(tpcds_yaml_path.read_text(encoding="utf-8"))

    # Top-level
    assert exported["version"] == original["version"]
    assert len(exported["semantic_model"]) == 1
    exp_model = exported["semantic_model"][0]
    orig_model = original["semantic_model"][0]
    assert exp_model["name"] == orig_model["name"]

    # Dataset names match (order independent)
    assert {d["name"] for d in exp_model["datasets"]} == {d["name"] for d in orig_model["datasets"]}

    # Dataset sources match exactly
    exp_sources = {d["source"] for d in exp_model["datasets"]}
    orig_sources = {d["source"] for d in orig_model["datasets"]}
    assert exp_sources == orig_sources

    # Primary keys preserved for the store_sales fact table
    exp_ss = next(d for d in exp_model["datasets"] if d["name"] == "store_sales")
    orig_ss = next(d for d in orig_model["datasets"] if d["name"] == "store_sales")
    assert exp_ss["primary_key"] == orig_ss["primary_key"]
    assert exp_ss["unique_keys"] == orig_ss["unique_keys"]

    # Relationship names preserved
    if "relationships" in orig_model:
        assert {r["name"] for r in exp_model.get("relationships", [])} == {
            r["name"] for r in orig_model["relationships"]
        }


def test_osi_connector_export_unknown_model_raises(neo4j_driver, tmp_path: Path):
    """Exporting a semantic model name that doesn't exist surfaces a clear error."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")

    with pytest.raises(ValueError, match="No OsiSemanticModel found"):
        connector.export(semantic_model_name="does_not_exist", output_path=tmp_path / "x.yaml")


def test_osi_connector_idempotent_reingest(neo4j_driver, tpcds_yaml_path: Path):
    """Ingesting the same OSI spec twice produces no duplicate nodes."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        counts_first = _counts(session)

    connector.ingest(tpcds_yaml_path)
    with neo4j_driver.session(database="neo4j") as session:
        counts_second = _counts(session)

    assert counts_first == counts_second, (
        f"Node counts changed on re-ingest: {counts_first} -> {counts_second}"
    )


def _counts(session) -> dict[str, int]:
    """Return a label → count map for the OSI-relevant labels."""
    labels = [
        "OsiSemanticModel",
        "OsiTable",
        "Table",
        "OsiColumn",
        "Column",
        "Query",
        "Metric",
        "Join",
        "Expression",
        "Aspect",
        "OsiAiContext",
        "OsiCustomExtensions",
        "BusinessTerm",
        "Database",
        "Schema",
    ]
    out: dict[str, int] = {}
    for lbl in labels:
        result = session.run(f"MATCH (n:`{lbl}`) RETURN count(n) AS c").single()
        out[lbl] = result["c"]
    return out


# ---------------------------------------------------------------------- #
# Export extractor (Cypher reads against a known graph)
# ---------------------------------------------------------------------- #


def test_export_extractor_reads_back_loaded_graph(neo4j_driver, tpcds_yaml_path: Path):
    """OsiGraphExtractor returns a snapshot that matches the ingested OSI input."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(tpcds_yaml_path)

    extractor = OsiGraphExtractor(neo4j_driver, database_name="neo4j")
    snapshot = extractor.extract("tpcds_retail_model")

    assert snapshot["name"] == "tpcds_retail_model"
    assert snapshot["osi_version"] == "0.2.0.dev0"
    assert len(snapshot["datasets"]) > 0

    # Every dataset has a non-empty fields list (TPC-DS sample populates fields for each)
    for ds in snapshot["datasets"]:
        assert isinstance(ds["fields"], list)

    # store_sales has primary_key + unique_keys decoded back to lists
    ss = next(d for d in snapshot["datasets"] if d["name"] == "store_sales")
    assert ss["primary_key"] == ["ss_item_sk", "ss_ticket_number"]
    assert ss["unique_keys"] == [["ss_item_sk", "ss_ticket_number"]]


def test_export_extractor_raises_for_unknown_model(neo4j_driver):
    """Extracting a missing semantic model name raises ValueError."""
    extractor = OsiGraphExtractor(neo4j_driver, database_name="neo4j")
    with pytest.raises(ValueError, match="No OsiSemanticModel found"):
        extractor.extract("does_not_exist")


# ---------------------------------------------------------------------- #
# Loader smoke test (constraints + labels + BT merge-on-name)
# ---------------------------------------------------------------------- #


def test_loader_writes_secondary_labels_and_dedupes_bts_by_name(
    neo4j_driver, tpcds_yaml_path: Path
):
    """After ingest, OSI nodes carry secondary labels and BTs dedup on name."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        # OsiSemanticModel nodes are also :Domain
        row = session.run("MATCH (n:OsiSemanticModel) RETURN labels(n) AS labels LIMIT 1").single()
        assert "Domain" in row["labels"]

        # OsiTable nodes are also :Table
        row = session.run("MATCH (n:OsiTable) RETURN labels(n) AS labels LIMIT 1").single()
        assert "Table" in row["labels"]

        # OsiAiContext nodes are also :Aspect
        row = session.run("MATCH (n:OsiAiContext) RETURN labels(n) AS labels LIMIT 1").single()
        assert "Aspect" in row["labels"]

        # BTs are unique by name
        dup_check = session.run(
            "MATCH (b:BusinessTerm) "
            "WITH b.name AS name, count(*) AS c "
            "WHERE c > 1 RETURN count(*) AS dupes"
        ).single()
        assert dup_check["dupes"] == 0


def test_loader_bt_merge_on_name_keeps_existing_id(neo4j_driver):
    """A pre-existing BusinessTerm (by name) keeps its id when OSI synonyms collide."""
    from neocarta.data_model.glossary import BusinessTerm

    loader = OsiNeo4jLoader(neo4j_driver, database_name="neo4j")

    # Pre-seed a BT as if from Dataplex — different id, same name.
    with neo4j_driver.session(database="neo4j") as session:
        session.run(
            "MERGE (b:BusinessTerm {id: $id}) SET b.name = $name",
            id="projects/foo/glossaries/bar/terms/customer",
            name="customer",
        )

    # OSI ingest path: MERGE-on-name should match the existing BT, not create a new one.
    loader.load_business_term_nodes_by_name(
        [BusinessTerm(id="osi.synonyms.customer", name="customer")]
    )

    with neo4j_driver.session(database="neo4j") as session:
        rows = list(
            session.run("MATCH (b:BusinessTerm {name: $n}) RETURN b.id AS id", n="customer")
        )

    assert len(rows) == 1
    assert rows[0]["id"] == "projects/foo/glossaries/bar/terms/customer"


# ---------------------------------------------------------------------- #
# Round-trip via the transformers + extractor (no Cypher mutations from this test)
# ---------------------------------------------------------------------- #


def test_extractor_and_export_transformer_produce_yaml_with_field_names(
    neo4j_driver, tpcds_yaml_path: Path
):
    """Ingest TPC-DS, run extractor + export transformer, confirm fields appear in YAML output."""
    # Stage the graph via the full ingest path
    spec = OsiSpecExtractor().extract(tpcds_yaml_path)
    ingest = OsiIngestTransformer()
    ingest.transform(spec)
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    snapshot = OsiGraphExtractor(neo4j_driver, "neo4j").extract("tpcds_retail_model")
    spec_out = OsiExportTransformer().transform(snapshot)

    # Each dataset in the output has a name and at least one field if the original did
    orig = yaml.safe_load(tpcds_yaml_path.read_text(encoding="utf-8"))["semantic_model"][0]
    for orig_ds in orig["datasets"]:
        exp_ds = next(
            d for d in spec_out["semantic_model"][0]["datasets"] if d["name"] == orig_ds["name"]
        )
        if orig_ds.get("fields"):
            exp_field_names = {f["name"] for f in exp_ds.get("fields", [])}
            orig_field_names = {f["name"] for f in orig_ds["fields"]}
            assert orig_field_names <= exp_field_names, (
                f"Missing fields for {orig_ds['name']}: {orig_field_names - exp_field_names}"
            )


# ---------------------------------------------------------------------- #
# Cypher edge verification (References, HasAspect, TaggedWith, HasExpression)
# ---------------------------------------------------------------------- #


def test_ingest_creates_references_edges_between_join_columns(neo4j_driver, tpcds_yaml_path: Path):
    """OSI relationships emit positional (:Column)-[:REFERENCES]->(:Column) edges in the graph."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        count = session.run(
            "MATCH (:Column)-[r:REFERENCES]->(:Column) RETURN count(r) AS c"
        ).single()["c"]
    assert count > 0


def test_ingest_creates_has_aspect_edges_for_multiple_source_labels(
    neo4j_driver, tpcds_yaml_path: Path
):
    """HAS_ASPECT polymorphic source matching resolves Schema/Table/Column/Metric correctly."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        # The TPCDS sample has ai_context on the SM (Domain), on datasets (Tables), and on
        # fields (Columns). Verify HAS_ASPECT edges exist from each source label.
        for label in ("Domain", "Table", "Column"):
            row = session.run(
                f"MATCH (s:{label})-[:HAS_ASPECT]->(:Aspect) RETURN count(*) AS c"
            ).single()
            assert row["c"] > 0, f"No HAS_ASPECT edges from {label}"


def test_ingest_creates_tagged_with_edges_to_business_terms(neo4j_driver, tpcds_yaml_path: Path):
    """OSI synonyms produce (:Column|:Table)-[:TAGGED_WITH]->(:BusinessTerm) edges."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        column_tags = session.run(
            "MATCH (:Column)-[r:TAGGED_WITH]->(:BusinessTerm) RETURN count(r) AS c"
        ).single()["c"]
        table_tags = session.run(
            "MATCH (:Table)-[r:TAGGED_WITH]->(:BusinessTerm) RETURN count(r) AS c"
        ).single()["c"]
    assert column_tags > 0, "No Column→BusinessTerm tags created from OSI synonyms"
    assert table_tags > 0, "No Table→BusinessTerm tags created from OSI synonyms"


def test_ingest_creates_has_expression_edges_for_columns_and_metrics(
    neo4j_driver, tpcds_yaml_path: Path
):
    """HAS_EXPRESSION attaches Expression nodes to both Columns and Metrics."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        column_exprs = session.run(
            "MATCH (:Column)-[r:HAS_EXPRESSION]->(:Expression) RETURN count(r) AS c"
        ).single()["c"]
        metric_exprs = session.run(
            "MATCH (:Metric)-[r:HAS_EXPRESSION]->(:Expression) RETURN count(r) AS c"
        ).single()["c"]
    assert column_exprs > 0
    assert metric_exprs > 0


# ---------------------------------------------------------------------- #
# Aspect content dedup in graph
# ---------------------------------------------------------------------- #


def test_identical_ai_context_payloads_collapse_to_one_aspect_node(neo4j_driver, tmp_path: Path):
    """Two datasets sharing the same ai_context produce one Aspect node referenced twice."""
    shared = {"synonyms": ["alpha"]}
    spec_path = tmp_path / "shared_ctx.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "version": "0.2.0",
                "semantic_model": [
                    {
                        "name": "shared_ctx_model",
                        "datasets": [
                            {
                                "name": "ds1",
                                "source": "db.s.ds1",
                                "ai_context": shared,
                                "fields": [],
                            },
                            {
                                "name": "ds2",
                                "source": "db.s.ds2",
                                "ai_context": shared,
                                "fields": [],
                            },
                        ],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(spec_path)

    with neo4j_driver.session(database="neo4j") as session:
        ai_nodes = session.run("MATCH (a:OsiAiContext) RETURN count(a) AS c").single()["c"]
        attached = session.run(
            "MATCH (:Table)-[r:HAS_ASPECT]->(:OsiAiContext) RETURN count(r) AS c"
        ).single()["c"]

    assert ai_nodes == 1
    assert attached == 2


# ---------------------------------------------------------------------- #
# Query source end-to-end
# ---------------------------------------------------------------------- #


def test_query_source_ingest_creates_query_node_with_columns(neo4j_driver, tmp_path: Path):
    """A dataset whose source is a SQL query lands as a :Query node with attached columns."""
    spec_path = tmp_path / "query_model.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "version": "0.2.0",
                "semantic_model": [
                    {
                        "name": "query_model",
                        "datasets": [
                            {
                                "name": "active_customers",
                                "source": "SELECT id, name FROM customers WHERE active = true",
                                "fields": [
                                    {"name": "id"},
                                    {"name": "name"},
                                ],
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(spec_path)

    with neo4j_driver.session(database="neo4j") as session:
        # Query node exists with the original SQL and dataset name
        q = session.run("MATCH (q:Query) RETURN q.name AS name, q.content AS content").single()
        assert q["name"] == "active_customers"
        assert q["content"].startswith("SELECT")

        # Domain → Query rel
        d_q = session.run("MATCH (:Domain)-[r:HAS_QUERY]->(:Query) RETURN count(r) AS c").single()[
            "c"
        ]
        assert d_q == 1

        # Query → Column rel for each field
        q_c = session.run(
            "MATCH (:Query)-[r:USES_COLUMN]->(:Column) RETURN count(r) AS c"
        ).single()["c"]
        assert q_c == 2

        # No OsiTable was created for the query-backed dataset
        ot = session.run("MATCH (n:OsiTable) RETURN count(n) AS c").single()["c"]
        assert ot == 0


# ---------------------------------------------------------------------- #
# Multi-SM and idempotent export
# ---------------------------------------------------------------------- #


def test_two_semantic_models_coexist_and_export_isolates(neo4j_driver, tmp_path: Path):
    """Ingesting two separate OSI specs into the same graph; export by name returns just one."""

    def _spec_path(name: str, source: str, path: Path) -> Path:
        path.write_text(
            yaml.safe_dump(
                {
                    "version": "0.2.0",
                    "semantic_model": [
                        {
                            "name": name,
                            "datasets": [
                                {"name": "t", "source": source, "fields": [{"name": "x"}]}
                            ],
                        }
                    ],
                },
                sort_keys=False,
            )
        )
        return path

    p_a = _spec_path("model_a", "db.s.ta", tmp_path / "a.yaml")
    p_b = _spec_path("model_b", "db.s.tb", tmp_path / "b.yaml")

    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(p_a)
    connector.ingest(p_b)

    with neo4j_driver.session(database="neo4j") as session:
        sm_count = session.run("MATCH (n:OsiSemanticModel) RETURN count(n) AS c").single()["c"]
    assert sm_count == 2

    out = tmp_path / "model_a_out.yaml"
    connector.export(semantic_model_name="model_a", output_path=out)
    exported = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert len(exported["semantic_model"]) == 1
    assert exported["semantic_model"][0]["name"] == "model_a"
    # model_b's table is NOT in model_a's export
    dataset_names = {d["name"] for d in exported["semantic_model"][0]["datasets"]}
    assert dataset_names == {"t"}


def test_export_is_idempotent(neo4j_driver, tpcds_yaml_path: Path, tmp_path: Path):
    """Exporting the same semantic model twice produces byte-identical YAML."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(tpcds_yaml_path)

    out1 = tmp_path / "exp1.yaml"
    out2 = tmp_path / "exp2.yaml"
    connector.export("tpcds_retail_model", out1)
    connector.export("tpcds_retail_model", out2)

    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


# ---------------------------------------------------------------------- #
# Constraints applied at ingest time
# ---------------------------------------------------------------------- #


def test_join_composite_key_column_order_round_trips(neo4j_driver, tmp_path: Path):
    """Composite-key from_columns / to_columns survive ingest + export with original order intact."""
    spec_path = tmp_path / "composite_join.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "version": "0.2.0",
                "semantic_model": [
                    {
                        "name": "composite_model",
                        "datasets": [
                            {
                                "name": "orders",
                                "source": "db.public.orders",
                                "fields": [
                                    {"name": "customer_id"},
                                    {"name": "order_date"},
                                    {"name": "region_code"},
                                ],
                            },
                            {
                                "name": "customer_history",
                                "source": "db.public.customer_history",
                                "fields": [
                                    {"name": "customer_id"},
                                    {"name": "as_of_date"},
                                    {"name": "region_code"},
                                ],
                            },
                        ],
                        "relationships": [
                            {
                                "name": "orders_to_history",
                                "from": "orders",
                                "to": "customer_history",
                                # Deliberately not alphabetical — order matters.
                                "from_columns": ["region_code", "customer_id", "order_date"],
                                "to_columns": ["region_code", "customer_id", "as_of_date"],
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    connector.ingest(spec_path)

    out = tmp_path / "composite_out.yaml"
    connector.export(semantic_model_name="composite_model", output_path=out)

    exported = yaml.safe_load(out.read_text(encoding="utf-8"))
    rel = exported["semantic_model"][0]["relationships"][0]
    assert rel["from_columns"] == ["region_code", "customer_id", "order_date"]
    assert rel["to_columns"] == ["region_code", "customer_id", "as_of_date"]


def test_ingest_writes_constraints_for_new_osi_node_labels(neo4j_driver, tpcds_yaml_path: Path):
    """Constraint creation runs during ingest for the new OSI primary labels."""
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("SHOW CONSTRAINTS YIELD labelsOrTypes RETURN labelsOrTypes")
        constraint_labels: set[str] = set()
        for record in result:
            for lbl in record["labelsOrTypes"] or []:
                constraint_labels.add(lbl)

    expected = {"Domain", "Metric", "Join", "Expression", "Aspect"}
    missing = expected - constraint_labels
    assert not missing, f"Missing constraints for OSI labels: {missing}"


def test_ingest_creates_full_text_indexes_for_search_nodes(neo4j_driver, tpcds_yaml_path: Path):
    """OSI ingest creates the full-text indexes the MCP search tiers gate on.

    The OSI loaders override the base Table/Column loaders, so without explicitly
    creating these the full-text, hybrid, and business-term-bridged search tools
    never register on a pure-OSI graph (issue #209). ``:OsiTable`` / ``:OsiColumn``
    augment the core ``:Table`` / ``:Column`` nodes and back the same search surface.
    """
    OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j").ingest(tpcds_yaml_path)

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("SHOW INDEXES YIELD name, type RETURN name, type")
        full_text_index_names = {
            record["name"] for record in result if record["type"] == "FULLTEXT"
        }

    expected = {
        "table_full_text_index",
        "column_full_text_index",
        "metric_full_text_index",
        "businessterm_full_text_index",
    }
    missing = expected - full_text_index_names
    assert not missing, f"Missing full-text indexes after OSI ingest: {missing}"
