"""LPG (Labeled Property Graph) structural data model nodes and relationships."""

import warnings

from .models import (
    Database,
    HasNode,
    HasRelationship,
    HasSchema,
    HasSourceNode,
    HasTargetNode,
    Node,
    NodeHasProperty,
    Property,
    Relationship,
    RelationshipHasProperty,
    Schema,
)

warnings.warn(
    "LPG data model components are an in-progress feature. There is no application in the current library version.",
    stacklevel=2,
)

__all__ = [
    "Database",
    "HasNode",
    "HasRelationship",
    "HasSchema",
    "HasSourceNode",
    "HasTargetNode",
    "Node",
    "NodeHasProperty",
    "Property",
    "Relationship",
    "RelationshipHasProperty",
    "Schema",
]
