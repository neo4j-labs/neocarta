"""The Databricks tags connector's normalized-schema mapping declaration.

This closes the one real coverage gap
[mapping-mechanism.md](../../../../docs/refactor/mapping-mechanism.md) §8.7 named for #298. The
S1.6 prototype consumed 10 of the contract's 13 tables and left the governance facet unconsumed,
so this connector scored **0 of its 3 families**. The gap was in what the prototype consumed, not
in the contract: both governance records bind here with **zero renames and zero hatches**.

- ``tag_key_info`` is ``[source, tag_key, tag_description]`` → ``GovernanceTagKeyRecord``
  (``source`` → ``tag_namespace``, ``tag_description`` → ``description``).
- ``tag_value_info`` is ``[source, tag_key, value_name]`` → ``GovernanceTagValueRecord``
  (``value_name`` → ``tag_value``).

The third family, ``has_value_option_relationships``, is correctly **not** a table: a value's key
path extends its key's, so the edge is derivable from the natural-key hierarchy exactly as the
containment edges are.

Two things stay outside the declaration on purpose. The system-prefix filter (``system.``,
``class.``, ``ai.``, ``sap.``) is a caller-facing ingest option, so it belongs in the extractor
where ``include_system_tags`` can reach it — not in a static declaration. And the extractor's own
dropping of value-less rows stays there too, because it is a fact about what Databricks returned.
"""

from neocarta.etl.metadata_normalizer import ConnectorMapping, SourceTable, static_scope
from neocarta.etl.metadata_normalizer.normalized_schema import (
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
)

DATABRICKS_TAGS = ConnectorMapping(
    tables={
        "governance_tag_keys": SourceTable(record=GovernanceTagKeyRecord, source="tag_key_info"),
        "governance_tag_values": SourceTable(
            record=GovernanceTagValueRecord, source="tag_value_info"
        ),
    },
    # Databricks tag *values* are bare — they carry no description — so writing one would
    # `SET description = null` and erase another source's (**D10**, the non-clobber contract).
    property_scope=static_scope(
        {
            "governance_tag_key_nodes": ["name", "description"],
            "governance_tag_value_nodes": ["name"],
        }
    ),
)
