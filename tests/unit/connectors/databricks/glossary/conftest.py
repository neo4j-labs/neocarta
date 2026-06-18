"""Fixtures for the Databricks glossary connector unit tests.

The Databricks SDK is mocked: a ``MagicMock`` ``WorkspaceClient`` returns
``SimpleNamespace`` objects shaped like the SDK's ``TagPolicy`` / ``Value`` and
metastore summary. No live workspace, no network, and no real PII in fixtures.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neocarta.connectors.databricks.glossary.extract import DatabricksGlossaryExtractor
from neocarta.connectors.databricks.glossary.transform import DatabricksGlossaryTransformer

# Raw metastore id the mocked workspace reports; the Glossary id derives from it.
METASTORE_ID = "aws:us-west-2:abc-123"


def _tag_policy(tag_key, description, policy_id, values):
    """Build a SimpleNamespace shaped like databricks.sdk.service.tags.TagPolicy."""
    return SimpleNamespace(
        tag_key=tag_key,
        description=description,
        id=policy_id,
        values=[SimpleNamespace(name=v) for v in values],
    )


def standard_policies():
    """A representative governed-tag set: enumerated, value-less, and a system tag."""
    return [
        _tag_policy("department", "Owning department", "tp-department", ["finance", "hr", "sales"]),
        _tag_policy("cost_center", "Finance cost center", "tp-cost-center", ["alpha", "beta"]),
        _tag_policy("free_form", "Free-form governed tag", "tp-free-form", []),
        _tag_policy(
            "system.certification_status", "Platform tag", "tp-system", ["certified", "deprecated"]
        ),
    ]


@pytest.fixture
def mock_workspace_client():
    """A MagicMock WorkspaceClient with governed tags and a resolvable metastore."""
    client = MagicMock()
    client.tag_policies.list_tag_policies.return_value = standard_policies()
    client.metastores.summary.return_value = SimpleNamespace(
        global_metastore_id=METASTORE_ID,
        metastore_id="abc-123",
        name="prod",
    )
    return client


@pytest.fixture
def extractor(mock_workspace_client):
    """A DatabricksGlossaryExtractor with the mocked workspace client."""
    return DatabricksGlossaryExtractor(mock_workspace_client)


@pytest.fixture
def extractor_with_cache(extractor):
    """An extractor whose cache is populated by a default extract() (system tags excluded)."""
    extractor.extract()
    return extractor


@pytest.fixture
def transformer():
    return DatabricksGlossaryTransformer()
