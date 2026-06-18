"""Integration test for the Databricks governed-tags glossary connector.

The Databricks SDK is mocked (a ``WorkspaceClient`` returning ``SimpleNamespace``
governed tags); Neo4j is real (a testcontainer via the shared ``neo4j_driver``
fixture). The full extract -> transform -> load pipeline runs against Neo4j and is
verified with Cypher, exercising the real ``Neo4jRDBMSLoader`` writes,
constraints, indexes, and the neocarta graph metadata node that the unit tests
mock out.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from neocarta.connectors.databricks import DatabricksGlossaryConnector
from neocarta.connectors.utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_glossary_id,
)

METASTORE_ID = "aws:us-west-2:abc-123"


def _tag_policy(tag_key, description, policy_id, values):
    return SimpleNamespace(
        tag_key=tag_key,
        description=description,
        id=policy_id,
        values=[SimpleNamespace(name=v) for v in values],
    )


def _mock_workspace_client():
    """A mock WorkspaceClient with governed tags and a resolvable metastore."""
    client = MagicMock()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("department", "Owning department", "tp-department", ["finance", "hr", "sales"]),
        _tag_policy("cost_center", "Finance cost center", "tp-cost-center", ["alpha", "beta"]),
        _tag_policy("free_form", "Free-form governed tag", "tp-free-form", []),
        _tag_policy("system.certification_status", "Platform tag", "tp-system", ["certified"]),
    ]
    client.metastores.summary.return_value = SimpleNamespace(
        global_metastore_id=METASTORE_ID, metastore_id="abc-123", name="prod"
    )
    return client


def _count(session, query, **params):
    return session.run(query, **params).single()["c"]


def test_ingest_loads_governed_tags_glossary(neo4j_driver):
    """A full ingest writes the Glossary/Category/BusinessTerm graph and HAS_* edges."""
    connector = DatabricksGlossaryConnector(
        workspace_client=_mock_workspace_client(), neo4j_driver=neo4j_driver
    )
    connector.ingest()  # system tags excluded by default

    gid = generate_glossary_id(METASTORE_ID)
    department_cat = generate_category_id(METASTORE_ID, "department")
    finance_term = generate_business_term_id(METASTORE_ID, "department", "finance")

    with neo4j_driver.session(database="neo4j") as session:
        # Nodes
        assert _count(session, "MATCH (g:Glossary {id:$id}) RETURN count(g) AS c", id=gid) == 1
        assert _count(session, "MATCH (c:Category) RETURN count(c) AS c") == 3
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 5

        # Glossary identity comes from the metastore id; resource_path keeps the raw id.
        g = session.run("MATCH (g:Glossary {id:$id}) RETURN g", id=gid).single()["g"]
        assert g["name"] == "Unity Catalog Governed Tags"
        assert g["resource_path"] == METASTORE_ID

        # Category carries the tag key's description + the tag-policy id.
        cat = session.run("MATCH (c:Category {id:$id}) RETURN c", id=department_cat).single()["c"]
        assert cat["name"] == "department"
        assert cat["description"] == "Owning department"
        assert cat["resource_path"] == "tp-department"

        # BusinessTerm is name-only: description / resource_path are never written
        # (the "omit undefined props" guarantee — they must be NULL, not "").
        term = session.run("MATCH (b:BusinessTerm {id:$id}) RETURN b", id=finance_term).single()[
            "b"
        ]
        assert term["name"] == "finance"
        assert term["description"] is None
        assert term["resource_path"] is None

        # Relationships
        assert (
            _count(session, "MATCH (:Glossary)-[:HAS_CATEGORY]->(:Category) RETURN count(*) AS c")
            == 3
        )
        assert (
            _count(
                session,
                "MATCH (:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm) RETURN count(*) AS c",
            )
            == 5
        )

        # The value-less governed tag is a Category with no BusinessTerm children.
        assert (
            _count(
                session,
                "MATCH (c:Category {name:'free_form'})-[:HAS_BUSINESS_TERM]->(b) "
                "RETURN count(b) AS c",
            )
            == 0
        )

        # System governed tags are excluded by default.
        assert (
            _count(
                session,
                "MATCH (c:Category {name:'system.certification_status'}) RETURN count(c) AS c",
            )
            == 0
        )

        # ingest() records the neocarta graph metadata node.
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1

        # The loader provisions a full-text index over BusinessTerm (backs MCP search).
        ft = session.run("SHOW FULLTEXT INDEXES YIELD labelsOrTypes RETURN labelsOrTypes").data()
        assert any("BusinessTerm" in (row["labelsOrTypes"] or []) for row in ft)

    # Idempotency: a second ingest MERGEs onto the same nodes (counts unchanged).
    connector.ingest()
    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 5
        assert _count(session, "MATCH (c:Category) RETURN count(c) AS c") == 3
        assert _count(session, "MATCH (g:Glossary) RETURN count(g) AS c") == 1


def test_value_id_normalization_collapses_variant_values(neo4j_driver):
    """Distinct values that normalize to the same slug collapse into one node.

    Governed-tag values are case-sensitive in Databricks, but the shared id scheme
    lowercases and maps spaces/hyphens to underscores, so values differing only in
    case/separator share a BusinessTerm id and MERGE into a single node. Pinned to
    document the behavior (see the connector README's limitations).
    """
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("risk", "Risk level", "tp-risk", ["High Risk", "high-risk", "high_risk"]),
    ]
    DatabricksGlossaryConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Three distinct values, one normalized id -> one node and one edge.
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 1
        assert (
            _count(
                session,
                "MATCH (:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm) RETURN count(*) AS c",
            )
            == 1
        )


def test_empty_governed_tags_does_not_crash(neo4j_driver):
    """No governed tags -> a lone (empty) Glossary + metadata node, no Category/terms."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = []
    DatabricksGlossaryConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (g:Glossary) RETURN count(g) AS c") == 1
        assert _count(session, "MATCH (c:Category) RETURN count(c) AS c") == 0
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 0
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1


def test_none_description_writes_null_not_empty_string(neo4j_driver):
    """A tag with no description writes Category.description as NULL (not '')."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("nodesc", None, "tp-nodesc", ["v"]),
    ]
    DatabricksGlossaryConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        desc = session.run("MATCH (c:Category {name:'nodesc'}) RETURN c.description AS d").single()[
            "d"
        ]
        assert desc is None


def test_ingest_include_system_tags(neo4j_driver):
    """With include_system_tags, the system.* governed tag becomes a Category + term."""
    connector = DatabricksGlossaryConnector(
        workspace_client=_mock_workspace_client(), neo4j_driver=neo4j_driver
    )
    connector.ingest(include_system_tags=True)

    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (c:Category) RETURN count(c) AS c") == 4
        assert (
            _count(
                session,
                "MATCH (c:Category {name:'system.certification_status'}) RETURN count(c) AS c",
            )
            == 1
        )
        assert (
            _count(session, "MATCH (b:BusinessTerm {name:'certified'}) RETURN count(b) AS c") == 1
        )
