"""Extract-stage typed dictionaries for the Databricks governance-tags connector.

These describe the flattened rows the extractor caches and the transformer
consumes. They are plain :class:`typing.TypedDict` shapes (not pydantic models):
the extractor builds them directly from the Databricks SDK ``TagPolicy`` objects
returned by ``WorkspaceClient.tag_policies.list_tag_policies()``.

A governed tag is an account-level controlled vocabulary: a ``tag_key`` with an
optional description and an optional list of allowed ``values``. One
:class:`TagPolicyValueInfo` row is produced per (governed tag, allowed value); a
governed tag declared with no allowed values produces a single row with
``value_name=None`` so the tag key still surfaces as a :GovernanceTagKey.
"""

from __future__ import annotations

from typing import TypedDict


class TagPolicyValueInfo(TypedDict):
    """One flattened (governed tag, allowed value) row.

    ``value_name`` is ``None`` for a governed tag that declares no allowed
    values (it still becomes a :GovernanceTagKey, with no :GovernanceTagValue
    options).
    """

    tag_key: str
    tag_description: str | None
    value_name: str | None
