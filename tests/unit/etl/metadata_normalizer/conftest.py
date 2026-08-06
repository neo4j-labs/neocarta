"""The connector sweep for the metadata-normalizer suite.

The offline drivers themselves live in ``tests/support/connectors/offline.py`` so the S1.6 spike
suite and this one build the *same* extractor objects rather than two lookalikes.
"""

import pytest

from tests.support.connectors.registry import DECLARATIONS

#: Every connector with a production declaration, as test ids.
CONNECTORS = tuple(declared.connector for declared in DECLARATIONS)


@pytest.fixture(params=CONNECTORS)
def connector(request):
    """Sweep every connector that has a declaration."""
    return request.param
