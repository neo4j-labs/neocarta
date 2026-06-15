"""The structural components of the LPG (Labeled Property Graph) metadata graph data model."""

from pydantic import BaseModel, Field, field_validator

from ..._validators import coerce_str_or_none, coerce_upper


class Database(BaseModel):
    """A Database node."""

    id: str = Field(..., description="The unique identifier for the database")
    name: str = Field(..., description="The name of the database")
    platform: str | None = Field(
        default=None, description="The platform of the database", examples=["GCP", "AWS", "AZURE"]
    )
    service: str | None = Field(
        default=None,
        description="The service running the database",
        examples=["NEO4J", "MEMGRAPH", "NEPTUNE"],
    )
    description: str | None = Field(default=None, description="The description of the database")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the database description"
    )

    _uppercase = field_validator("platform", "service", mode="after")(coerce_upper)
    _normalize = field_validator("description", "platform", "service", mode="before")(
        coerce_str_or_none
    )


class Schema(BaseModel):
    """A Schema node."""

    id: str = Field(..., description="The unique identifier for the schema")
    name: str = Field(..., description="The name of the schema")
    description: str | None = Field(default=None, description="The description of the schema")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the schema description"
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class Node(BaseModel):
    """A Node node (represents a node label in the LPG)."""

    id: str = Field(..., description="The unique identifier for the node label")
    label: str = Field(..., description="The primary label of the node")
    additional_labels: list[str] | None = Field(
        default=None, description="Additional labels on the node"
    )
    description: str | None = Field(default=None, description="The description of the node label")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the node description"
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class Relationship(BaseModel):
    """A Relationship node (represents a relationship type in the LPG)."""

    id: str = Field(..., description="The unique identifier for the relationship type")
    type: str = Field(..., description="The type of the relationship")
    description: str | None = Field(
        default=None, description="The description of the relationship type"
    )
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the relationship description"
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class Property(BaseModel):
    """A Property node."""

    id: str = Field(..., description="The unique identifier for the property")
    name: str = Field(..., description="The name of the property")
    type: str | None = Field(default=None, description="The data type of the property")
    description: str | None = Field(default=None, description="The description of the property")
    unique: bool = Field(
        default=False, description="Whether the property has a uniqueness constraint"
    )
    nullable: bool = Field(default=True, description="Whether the property can be null")
    indexed: bool = Field(default=False, description="Whether the property is indexed")
    existence: bool = Field(
        default=False, description="Whether the property has an existence constraint"
    )
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the property description"
    )

    _normalize = field_validator("description", "type", mode="before")(coerce_str_or_none)


class HasSchema(BaseModel):
    """
    A relationship between a database and a schema
    (Database)-[:HAS_SCHEMA]->(Schema).
    """

    database_id: str = Field(..., description="The unique identifier for the database")
    schema_id: str = Field(..., description="The unique identifier for the schema")


class HasNode(BaseModel):
    """
    A relationship between a schema and a node label
    (Schema)-[:HAS_NODE]->(Node).
    """

    schema_id: str = Field(..., description="The unique identifier for the schema")
    node_id: str = Field(..., description="The unique identifier for the node label")


class HasRelationship(BaseModel):
    """
    A relationship between a schema and a relationship type
    (Schema)-[:HAS_RELATIONSHIP]->(Relationship).
    """

    schema_id: str = Field(..., description="The unique identifier for the schema")
    relationship_id: str = Field(..., description="The unique identifier for the relationship type")


class HasSourceNode(BaseModel):
    """
    A relationship between a relationship type and its source node label
    (Relationship)-[:HAS_SOURCE_NODE]->(Node).
    """

    relationship_id: str = Field(..., description="The unique identifier for the relationship type")
    node_id: str = Field(..., description="The unique identifier for the source node label")


class HasTargetNode(BaseModel):
    """
    A relationship between a relationship type and its target node label
    (Relationship)-[:HAS_TARGET_NODE]->(Node).
    """

    relationship_id: str = Field(..., description="The unique identifier for the relationship type")
    node_id: str = Field(..., description="The unique identifier for the target node label")


class NodeHasProperty(BaseModel):
    """
    A relationship between a node and a property
    (Node)-[:HAS_PROPERTY]->(Property).
    """

    source_id: str = Field(..., description="The unique identifier for the source node")
    property_id: str = Field(..., description="The unique identifier for the property")


class RelationshipHasProperty(BaseModel):
    """
    A relationship between a relationship and a property
    (Relationship)-[:HAS_PROPERTY]->(Property).
    """

    source_id: str = Field(..., description="The unique identifier for the source relationship")
    property_id: str = Field(..., description="The unique identifier for the property")
