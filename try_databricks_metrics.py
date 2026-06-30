"""Local one-command tester for the Databricks metrics connector — NOT part of the PR.

Does everything end to end so you don't have to touch the Databricks UI or juggle
.env: connects to your Databricks workspace, CREATEs a temporary metric view
(sourced from the public ``samples.tpch.orders``), runs the real connector into a
Neo4j, prints the resulting graph, then DROPs the view and cleans up.

Run from the repo root:

    uv run python try_databricks_metrics.py                 # local throwaway Neo4j (Docker/colima)
    uv run python try_databricks_metrics.py --search        # also embeddings + a live semantic search
    uv run python try_databricks_metrics.py --aura          # use your .env Neo4j (AuraDB), scoped cleanup
    uv run python try_databricks_metrics.py --keep          # leave the view + graph for inspection

Reads from .env: DATABRICKS_HOST, DATABRICKS_TOKEN (required); optional
DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH / DATABRICKS_CATALOG /
DATABRICKS_SCHEMA (auto-derived / auto-discovered if absent). --aura also needs
NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD. --search needs OPENAI_API_KEY.
"""

import argparse
import os

# Default the Docker socket to colima so the local-Neo4j mode works out of the box.
os.environ.setdefault("DOCKER_HOST", "unix:///Users/rajvardhan/.colima/default/docker.sock")
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from databricks import sql  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

from neocarta import NodeLabel  # noqa: E402
from neocarta.connectors.databricks import DatabricksMetricsConnector  # noqa: E402

VIEW = "neocarta_try_metrics"
YAML = """version: "1.1"
comment: Neocarta try metric view
source: samples.tpch.orders
dimensions:
  - name: order_status
    expr: o_orderstatus
    display_name: Order Status
    synonyms: [status, fulfillment status]
measures:
  - name: total_revenue
    expr: SUM(o_totalprice)
    comment: Gross revenue across all orders
    display_name: Total Revenue
    synonyms: [revenue, sales]
  - name: order_count
    expr: COUNT(1)
    comment: Number of orders
"""


def main() -> None:
    """Run the end-to-end Databricks-metrics try."""
    parser = argparse.ArgumentParser(description="Try the Databricks metrics connector end to end.")
    parser.add_argument("--aura", action="store_true", help="Use the .env Neo4j instead of a local container.")
    parser.add_argument("--search", action="store_true", help="Also run embeddings + a live semantic search.")
    parser.add_argument("--keep", action="store_true", help="Leave the metric view and graph in place.")
    args = parser.parse_args()

    host = os.environ["DATABRICKS_HOST"]
    token = os.environ["DATABRICKS_TOKEN"]
    server = os.getenv("DATABRICKS_SERVER_HOSTNAME") or host.replace("https://", "").replace(
        "http://", ""
    ).rstrip("/")
    catalog = os.getenv("DATABRICKS_CATALOG", "workspace")
    schema = os.getenv("DATABRICKS_SCHEMA", "default")

    http_path = os.getenv("DATABRICKS_HTTP_PATH")
    if not http_path:
        wh = next(iter(WorkspaceClient(host=host, token=token).warehouses.list()))
        http_path = f"/sql/1.0/warehouses/{wh.id}"
        print(f"[databricks] auto-discovered warehouse {wh.id} ({wh.state})")

    print(f"[databricks] connecting to {server} {http_path} ...")
    conn = sql.connect(server_hostname=server, http_path=http_path, access_token=token)

    container = None
    if args.aura:
        neo4j_db = os.getenv("NEO4J_DATABASE", "neo4j")
        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        print(f"[neo4j] using .env Neo4j (database={neo4j_db})")
    else:
        from testcontainers.neo4j import Neo4jContainer

        print("[neo4j] starting a throwaway local Neo4j container ...")
        container = Neo4jContainer("neo4j:5.26.23")
        container.start()
        neo4j_db = "neo4j"
        driver = GraphDatabase.driver(
            container.get_connection_url(), auth=(container.username, container.password)
        )
        print(f"[neo4j] up at {container.get_connection_url()}")

    def execute(sql_text: str) -> None:
        cur = conn.cursor()
        try:
            cur.execute(sql_text)
        finally:
            cur.close()

    def cy(q: str, **p: object) -> list:
        recs, _, _ = driver.execute_query(q, database_=neo4j_db, **p)
        return recs

    full_name = f"{catalog}.{schema}.{VIEW}"
    try:
        print(f"[databricks] creating metric view {full_name} ...")
        execute(
            f"CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`{VIEW}`\n"
            f"WITH METRICS\nLANGUAGE YAML\nAS $$\n{YAML}\n$$"
        )

        print("\n[ingest] running DatabricksMetricsConnector.ingest() ...")
        DatabricksMetricsConnector(
            connection=conn, catalog=catalog, neo4j_driver=driver, database_name=neo4j_db
        ).ingest(schema=schema)
        print("[ingest] done")

        print("\n[graph] domains and metrics:")
        for rec in cy(
            "MATCH (d:Domain:OsiSemanticModel {id:$id})-[:HAS_METRIC]->(m:Metric) "
            "RETURN d.name AS domain, collect(m.name) AS metrics",
            id=full_name,
        ):
            print(f"  {rec['domain']} -> {sorted(rec['metrics'])}")

        print("\n[graph] metric expressions:")
        for rec in cy(
            "MATCH (m:Metric)-[:HAS_EXPRESSION]->(e:Expression) "
            "WHERE m.id STARTS WITH $p RETURN m.name AS name, e.dialect AS d, e.expression AS x "
            "ORDER BY name",
            p=full_name,
        ):
            print(f"  {rec['name']}: [{rec['d']}] {rec['x']}")

        print("\n[graph] dimensions:")
        for rec in cy(
            "MATCH (t:Table:OsiTable {id:$id})-[:HAS_COLUMN]->(c:Column:OsiColumn) "
            "RETURN c.name AS name, c.label AS label ORDER BY name",
            id=full_name,
        ):
            print(f"  {rec['name']} (label={rec['label']!r})")

        print("\n[graph] synonyms -> business terms:")
        for rec in cy(
            "MATCH (m:Metric)-[:TAGGED_WITH]->(b:BusinessTerm) "
            "WHERE m.id STARTS WITH $p RETURN m.name AS name, collect(b.name) AS terms ORDER BY name",
            p=full_name,
        ):
            print(f"  {rec['name']} <- {sorted(rec['terms'])}")

        if args.search:
            from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

            print("\n[search] generating embeddings + running a live metric vector search ...")
            embedder = LiteLLMEmbeddingsConnector(
                neo4j_driver=driver,
                embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                database_name=neo4j_db,
            )
            embedder.run(
                node_labels=[
                    NodeLabel.DOMAIN,
                    NodeLabel.TABLE,
                    NodeLabel.COLUMN,
                    NodeLabel.METRIC,
                ]
            )
            qvec = embedder._create_embedding_sync("how much money did we make from sales")
            print("  query: 'how much money did we make from sales'")
            for rec in cy(
                "CALL db.index.vector.queryNodes('metric_vector_index', 5, $v) "
                "YIELD node, score RETURN node.name AS name, score ORDER BY score DESC",
                v=qvec,
            ):
                print(f"    {rec['score']:.3f}  {rec['name']}")

        print("\n[done] success")
    finally:
        if args.keep:
            print(f"\n[keep] leaving {full_name} and its graph in place.")
        else:
            print("\n[cleanup] dropping the metric view ...")
            try:
                execute(f"DROP VIEW IF EXISTS `{catalog}`.`{schema}`.`{VIEW}`")
            except Exception as exc:  # noqa: BLE001
                print(f"  drop failed: {type(exc).__name__}")
            if args.aura:
                # Scoped: delete only this view's subgraph + any now-orphan business terms.
                cy("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", p=full_name)
                cy("MATCH (b:BusinessTerm) WHERE NOT (b)<-[:TAGGED_WITH]-() DETACH DELETE b")
                print("[cleanup] removed the test subgraph from your Neo4j (scoped).")
        conn.close()
        driver.close()
        if container is not None:
            container.stop()
            print("[cleanup] stopped local Neo4j container.")


if __name__ == "__main__":
    main()
