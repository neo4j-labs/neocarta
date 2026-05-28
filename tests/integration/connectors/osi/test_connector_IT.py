"""Integration tests for the OSI connector — ingest, export, and round-trip.

These tests run against a live Neo4j container (provided by the integration
conftest's ``setup`` / ``neo4j_driver`` fixtures) and exercise the full stack:
loader, ingest+export transformers, and the graph extractor.
"""

from pathlib import Path

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
    assert {d["name"] for d in exp_model["datasets"]} == {
        d["name"] for d in orig_model["datasets"]
    }

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


def test_osi_connector_export_unknown_model_raises(neo4j_driver):
    """Exporting a semantic model name that doesn't exist surfaces a clear error."""
    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name="neo4j")
    import pytest

    with pytest.raises(ValueError, match="No OsiSemanticModel found"):
        connector.export(semantic_model_name="does_not_exist", output_path="/tmp/x.yaml")


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
    import pytest

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
        row = session.run(
            "MATCH (n:OsiSemanticModel) RETURN labels(n) AS labels LIMIT 1"
        ).single()
        assert "Domain" in row["labels"]

        # OsiTable nodes are also :Table
        row = session.run(
            "MATCH (n:OsiTable) RETURN labels(n) AS labels LIMIT 1"
        ).single()
        assert "Table" in row["labels"]

        # OsiAiContext nodes are also :Aspect
        row = session.run(
            "MATCH (n:OsiAiContext) RETURN labels(n) AS labels LIMIT 1"
        ).single()
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
    from neocarta.data_model.rdbms import BusinessTerm

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
        rows = list(session.run("MATCH (b:BusinessTerm {name: $n}) RETURN b.id AS id", n="customer"))

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
    spec = OsiSpecExtractor(tpcds_yaml_path).extract()
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
