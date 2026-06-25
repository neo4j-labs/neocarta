"""Integration test for the Databricks governance-tags connector.

The Databricks SDK is mocked (a ``WorkspaceClient`` returning ``SimpleNamespace``
governed tags); Neo4j is real (a testcontainer via the shared ``neo4j_driver``
fixture). The full extract -> transform -> load pipeline runs against Neo4j and is
verified with Cypher, exercising the real ``Neo4jRDBMSLoader`` writes,
constraints, indexes, and the neocarta graph metadata node that the unit tests
mock out. This covers the definition layer (GovernanceTagKey / GovernanceTagValue
/ HAS_VALUE_OPTION); the instance/assignment layer is a planned follow-up.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from neocarta.connectors.databricks import DatabricksTagsConnector
from neocarta.connectors.utils.generate_id import (
    generate_governance_tag_key_id,
    generate_governance_tag_value_id,
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


def test_ingest_loads_governance_tag_definitions(neo4j_driver):
    """A full ingest writes the GovernanceTagKey/Value graph and HAS_VALUE_OPTION edges."""
    connector = DatabricksTagsConnector(
        workspace_client=_mock_workspace_client(), neo4j_driver=neo4j_driver
    )
    connector.ingest()  # system tags excluded by default

    department_key = generate_governance_tag_key_id(METASTORE_ID, "department")
    finance_value = generate_governance_tag_value_id(METASTORE_ID, "department", "finance")

    with neo4j_driver.session(database="neo4j") as session:
        # Nodes
        assert _count(session, "MATCH (k:GovernanceTagKey) RETURN count(k) AS c") == 3
        assert _count(session, "MATCH (v:GovernanceTagValue) RETURN count(v) AS c") == 5

        # Key carries the tag's name + description (the searchable surface).
        key = session.run(
            "MATCH (k:GovernanceTagKey {id:$id}) RETURN k", id=department_key
        ).single()["k"]
        assert key["name"] == "department"
        assert key["description"] == "Owning department"

        # Value is name-only: description is never written (the "omit undefined
        # props" guarantee — it must be NULL, not "").
        val = session.run(
            "MATCH (v:GovernanceTagValue {id:$id}) RETURN v", id=finance_value
        ).single()["v"]
        assert val["name"] == "finance"
        assert val["description"] is None

        # Relationships
        assert (
            _count(
                session,
                "MATCH (:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue) "
                "RETURN count(*) AS c",
            )
            == 5
        )

        # The value-less governed tag is a key with no value options.
        assert (
            _count(
                session,
                "MATCH (k:GovernanceTagKey {name:'free_form'})-[:HAS_VALUE_OPTION]->(v) "
                "RETURN count(v) AS c",
            )
            == 0
        )

        # System governed tags are excluded by default.
        assert (
            _count(
                session,
                "MATCH (k:GovernanceTagKey {name:'system.certification_status'}) "
                "RETURN count(k) AS c",
            )
            == 0
        )

        # ingest() records the neocarta graph metadata node.
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1

        # The loader provisions a full-text index over GovernanceTagKey (the search surface).
        ft = session.run("SHOW FULLTEXT INDEXES YIELD labelsOrTypes RETURN labelsOrTypes").data()
        assert any("GovernanceTagKey" in (row["labelsOrTypes"] or []) for row in ft)

    # Idempotency: a second ingest MERGEs onto the same nodes (counts unchanged).
    connector.ingest()
    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (k:GovernanceTagKey) RETURN count(k) AS c") == 3
        assert _count(session, "MATCH (v:GovernanceTagValue) RETURN count(v) AS c") == 5


def test_value_id_hashing_keeps_variant_values_distinct(neo4j_driver):
    """Case/separator-variant values stay distinct because the value id is hashed.

    Governed-tag values are case-sensitive in Databricks. The value segment of the
    GovernanceTagValue id is md5-hashed (not normalized), so values differing only in
    case/separator get distinct ids and DON'T collapse — three values yield three
    nodes and three HAS_VALUE_OPTION edges. (Keys are still normalized and may
    collapse; see the connector README's limitations.)
    """
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("risk", "Risk level", "tp-risk", ["High Risk", "high-risk", "high_risk"]),
    ]
    DatabricksTagsConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Three distinct values, three distinct hashed ids -> three nodes and three edges.
        assert _count(session, "MATCH (v:GovernanceTagValue) RETURN count(v) AS c") == 3
        assert (
            _count(
                session,
                "MATCH (:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue) "
                "RETURN count(*) AS c",
            )
            == 3
        )
        # The original values are preserved on the node names.
        names = {r["n"] for r in session.run("MATCH (v:GovernanceTagValue) RETURN v.name AS n")}
        assert names == {"High Risk", "high-risk", "high_risk"}


def test_empty_governed_tags_does_not_crash(neo4j_driver):
    """No governed tags -> just the metadata node, no keys/values."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = []
    DatabricksTagsConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (k:GovernanceTagKey) RETURN count(k) AS c") == 0
        assert _count(session, "MATCH (v:GovernanceTagValue) RETURN count(v) AS c") == 0
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1


def test_none_description_writes_null_not_empty_string(neo4j_driver):
    """A tag with no description writes GovernanceTagKey.description as NULL (not '')."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("nodesc", None, "tp-nodesc", ["v"]),
    ]
    DatabricksTagsConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        desc = session.run(
            "MATCH (k:GovernanceTagKey {name:'nodesc'}) RETURN k.description AS d"
        ).single()["d"]
        assert desc is None


def test_ingest_include_system_tags(neo4j_driver):
    """With include_system_tags, the system.* governed tag becomes a key + value."""
    connector = DatabricksTagsConnector(
        workspace_client=_mock_workspace_client(), neo4j_driver=neo4j_driver
    )
    connector.ingest(include_system_tags=True)

    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (k:GovernanceTagKey) RETURN count(k) AS c") == 4
        assert (
            _count(
                session,
                "MATCH (k:GovernanceTagKey {name:'system.certification_status'}) "
                "RETURN count(k) AS c",
            )
            == 1
        )
        assert (
            _count(session, "MATCH (v:GovernanceTagValue {name:'certified'}) RETURN count(v) AS c")
            == 1
        )


def test_platform_prefix_tags_excluded_by_default(neo4j_driver):
    """A class.* platform tag is dropped by default but a user tag lands."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("department", "Owning department", "tp-dep", ["finance"]),
        _tag_policy("class.pii", "Auto-applied classification", "tp-class", ["high"]),
        _tag_policy("ai.model_family", "Auto-applied", "tp-ai", ["gpt"]),
    ]
    DatabricksTagsConnector(workspace_client=client, neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        names = {r["n"] for r in session.run("MATCH (k:GovernanceTagKey) RETURN k.name AS n")}
        assert names == {"department"}


def test_custom_system_prefixes_keeps_platform_tags(neo4j_driver):
    """Narrowing the prefix set lets class./ai. tags through."""
    client = _mock_workspace_client()
    client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("department", "Owning department", "tp-dep", ["finance"]),
        _tag_policy("class.pii", "Auto-applied classification", "tp-class", ["high"]),
    ]
    DatabricksTagsConnector(
        workspace_client=client, neo4j_driver=neo4j_driver, system_prefixes=("system.",)
    ).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        names = {r["n"] for r in session.run("MATCH (k:GovernanceTagKey) RETURN k.name AS n")}
        assert names == {"department", "class.pii"}
