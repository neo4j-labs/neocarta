"""Integration tests for the split Collibra connectors against a real Neo4j.

A fake Collibra client supplies a small instance (Sales community → Warehouse
schema with a table + columns, and a Sales Glossary with a business term tagged
onto a column). Both sub-connectors ingest into the Neo4j testcontainer so we can
assert the dual subtype labels, the hierarchy, the ``collibra_id`` index, and the
cross-sub-connector ``TAGGED_WITH`` edge resolved by ``collibra_id``.
"""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.collibra.glossary import CollibraGlossaryConnector
from neocarta.connectors.collibra.schema import CollibraSchemaConnector

_ASSET_TYPES = {"at-table": "Table", "at-col": "Column", "at-bt": "Business Term"}
_DOMAIN_TYPES = {"dt-phys": "Physical Data Dictionary", "dt-gloss": "Business Glossary"}
_RELATION_TYPES = {
    "rt-contains": "Table contains Column",
    "rt-tag": "Asset associated with Business Term",
}
_COMMUNITIES = [{"id": "c1", "name": "Sales", "description": None}]
_DOMAINS = [
    {
        "id": "dom-wh",
        "name": "Warehouse",
        "description": None,
        "community": {"id": "c1"},
        "type": {"id": "dt-phys", "name": "Physical Data Dictionary"},
    },
    {
        "id": "dom-g",
        "name": "Sales Glossary",
        "description": None,
        "community": {"id": "c1"},
        "type": {"id": "dt-gloss", "name": "Business Glossary"},
    },
]
_ASSETS = {
    "dom-wh": [
        {
            "id": "a-orders",
            "name": "orders",
            "displayName": "orders",
            "domain": {"id": "dom-wh"},
            "type": {"id": "at-table", "name": "Table"},
            "status": {"name": "Accepted"},
        },
        {
            "id": "a-oid",
            "name": "order_id",
            "displayName": "order_id",
            "domain": {"id": "dom-wh"},
            "type": {"id": "at-col", "name": "Column"},
            "status": {"name": "Accepted"},
        },
    ],
    "dom-g": [
        {
            "id": "a-bt",
            "name": "Order",
            "displayName": "Order",
            "domain": {"id": "dom-g"},
            "type": {"id": "at-bt", "name": "Business Term"},
            "status": {"name": "Accepted"},
        },
    ],
}
_RELATIONS = {
    "rt-contains": [
        {
            "id": "r1",
            "source": {"id": "a-orders"},
            "target": {"id": "a-oid"},
            "type": {"id": "rt-contains"},
        },
    ],
    "rt-tag": [
        {"id": "r2", "source": {"id": "a-oid"}, "target": {"id": "a-bt"}, "type": {"id": "rt-tag"}},
    ],
}


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.discover_types.return_value = (_ASSET_TYPES, _DOMAIN_TYPES, _RELATION_TYPES)

    def get_paginated(path, params=None):
        params = params or {}
        if path == "/rest/2.0/communities":
            return _COMMUNITIES
        if path == "/rest/2.0/domains":
            return _DOMAINS
        if path == "/rest/2.0/assets":
            return _ASSETS.get(params.get("domainId"), [])
        if path == "/rest/2.0/relations":
            return _RELATIONS.get(params.get("relationTypeId"), [])
        return []

    client.get_paginated.side_effect = get_paginated
    return client


@pytest.mark.integration
def test_collibra_split_ingest_into_neo4j(neo4j_driver):
    """Schema then glossary ingest produce subtype labels, hierarchy, index, and tags."""
    CollibraSchemaConnector(client=_fake_client(), neo4j_driver=neo4j_driver).ingest()
    CollibraGlossaryConnector(client=_fake_client(), neo4j_driver=neo4j_driver).ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Table nodes carry both the core and Collibra subtype labels.
        labels = session.run("MATCH (n:CollibraTable) RETURN labels(n) AS labels LIMIT 1").single()[
            "labels"
        ]
        assert "Table" in labels
        assert "CollibraTable" in labels

        # Hierarchy: the column is attached to its parent table.
        has_col = session.run(
            "MATCH (:Table)-[r:HAS_COLUMN]->(:Column) RETURN count(r) AS c"
        ).single()["c"]
        assert has_col == 1

        # Cross-sub-connector TAGGED_WITH: column → business term, matched by collibra_id.
        tagged = session.run(
            "MATCH (c:CollibraColumn)-[:TAGGED_WITH]->(b:BusinessTerm) "
            "RETURN c.collibra_id AS col, b.name AS term"
        ).single()
        assert tagged["col"] == "a-oid"
        assert tagged["term"] == "Order"

        # A collibra_id range index exists for the column subtype label.
        indexes = session.run(
            "SHOW INDEXES YIELD labelsOrTypes, properties "
            "RETURN labelsOrTypes AS labels, properties AS props"
        )
        assert any(
            row["labels"] == ["CollibraColumn"] and row["props"] == ["collibra_id"]
            for row in indexes
        )
