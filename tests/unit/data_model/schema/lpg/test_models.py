"""Unit tests for LPG core data model components."""

import numpy as np
import pytest
from pandas import NA
from pydantic import ValidationError

from neocarta.data_model.schema.lpg import (
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


def test_database_valid():
    """Test creating a valid Database node."""
    db = Database(id="db1", name="MyGraph", platform="gcp", service="neo4j")
    assert db.id == "db1"
    assert db.name == "MyGraph"
    assert db.platform == "GCP"
    assert db.service == "NEO4J"


def test_database_uppercase_validation():
    """Test that platform and service are converted to uppercase."""
    db = Database(id="db1", name="MyGraph", platform="AURA", service="NEO4J")
    assert db.platform == "AURA"
    assert db.service == "NEO4J"


def test_database_nan_handling():
    """Test that NaN values are converted to None."""
    db = Database(id="db1", name="MyGraph", description=NA)
    assert db.description is None


def test_schema_valid():
    """Test creating a valid Schema node."""
    schema = Schema(id="s1", name="public", description="Public schema")
    assert schema.id == "s1"
    assert schema.name == "public"
    assert schema.description == "Public schema"


def test_schema_nan_handling():
    """Test that NaN values are converted to None."""
    schema = Schema(id="s1", name="public", description=NA)
    assert schema.description is None


def test_node_valid():
    """Test creating a valid Node node."""
    node = Node(id="n1", label="Person", additional_labels=["User", "Admin"])
    assert node.id == "n1"
    assert node.label == "Person"
    assert node.additional_labels == ["User", "Admin"]


def test_node_no_additional_labels():
    """Test Node without additional labels."""
    node = Node(id="n1", label="Person")
    assert node.additional_labels is None


def test_relationship_valid():
    """Test creating a valid Relationship node."""
    rel = Relationship(id="r1", type="KNOWS", description="Knows relationship")
    assert rel.id == "r1"
    assert rel.type == "KNOWS"
    assert rel.description == "Knows relationship"


def test_property_valid():
    """Test creating a valid Property node."""
    prop = Property(
        id="p1",
        name="email",
        type="STRING",
        unique=True,
        nullable=False,
        indexed=True,
        existence=True,
    )
    assert prop.id == "p1"
    assert prop.name == "email"
    assert prop.type == "STRING"
    assert prop.unique is True
    assert prop.nullable is False
    assert prop.indexed is True
    assert prop.existence is True


def test_property_defaults():
    """Test Property default values."""
    prop = Property(id="p1", name="age")
    assert prop.unique is False
    assert prop.nullable is True
    assert prop.indexed is False
    assert prop.existence is False


def test_has_schema_valid():
    """Test creating a valid HasSchema relationship."""
    rel = HasSchema(database_id="db1", schema_id="s1")
    assert rel.database_id == "db1"
    assert rel.schema_id == "s1"


def test_has_node_valid():
    """Test creating a valid HasNode relationship."""
    rel = HasNode(schema_id="s1", node_id="n1")
    assert rel.schema_id == "s1"
    assert rel.node_id == "n1"


def test_has_relationship_valid():
    """Test creating a valid HasRelationship relationship."""
    rel = HasRelationship(schema_id="s1", relationship_id="r1")
    assert rel.schema_id == "s1"
    assert rel.relationship_id == "r1"


def test_has_source_node_valid():
    """Test creating a valid HasSourceNode relationship."""
    rel = HasSourceNode(relationship_id="r1", node_id="n1")
    assert rel.relationship_id == "r1"
    assert rel.node_id == "n1"


def test_has_target_node_valid():
    """Test creating a valid HasTargetNode relationship."""
    rel = HasTargetNode(relationship_id="r1", node_id="n2")
    assert rel.relationship_id == "r1"
    assert rel.node_id == "n2"


def test_node_has_property_valid():
    """Test creating a valid NodeHasProperty relationship."""
    rel = NodeHasProperty(source_id="n1", property_id="p1")
    assert rel.source_id == "n1"
    assert rel.property_id == "p1"


def test_relationship_has_property_valid():
    """Test creating a valid RelationshipHasProperty relationship."""
    rel = RelationshipHasProperty(source_id="r1", property_id="p1")
    assert rel.source_id == "r1"
    assert rel.property_id == "p1"


def test_database_missing_required_fields():
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        Database(id="db1")


def test_property_with_embedding():
    """Test Property with embedding vector."""
    embedding = [0.1, 0.2, 0.3]
    prop = Property(id="p1", name="name", embedding=embedding)
    assert prop.embedding == embedding


def test_database_numpy_nan_handling():
    """Test that numpy.nan values are converted to None."""
    db = Database(id="db1", name="MyGraph", description=np.nan, platform=np.nan)
    assert db.description is None
    assert db.platform is None


def test_schema_numpy_nan_handling():
    """Test that numpy.nan values are converted to None."""
    schema = Schema(id="s1", name="public", description=np.nan)
    assert schema.description is None


def test_node_numpy_nan_handling():
    """Test that numpy.nan values are converted to None."""
    node = Node(id="n1", label="Person", description=np.nan)
    assert node.description is None


def test_relationship_numpy_nan_handling():
    """Test that numpy.nan values are converted to None."""
    rel = Relationship(id="r1", type="KNOWS", description=np.nan)
    assert rel.description is None


def test_property_numpy_nan_handling():
    """Test that numpy.nan values are converted to None."""
    prop = Property(id="p1", name="email", type=np.nan, description=np.nan)
    assert prop.type is None
    assert prop.description is None


def test_database_optional_defaults():
    """Test that optional fields default to None."""
    db = Database(id="db1", name="MyGraph")
    assert db.platform is None
    assert db.service is None
    assert db.description is None
    assert db.embedding is None


def test_schema_optional_defaults():
    """Test that optional fields default to None."""
    schema = Schema(id="s1", name="public")
    assert schema.description is None
    assert schema.embedding is None


def test_node_optional_defaults():
    """Test that optional fields default to None."""
    node = Node(id="n1", label="Person")
    assert node.additional_labels is None
    assert node.description is None
    assert node.embedding is None


def test_relationship_optional_defaults():
    """Test that optional fields default to None."""
    rel = Relationship(id="r1", type="KNOWS")
    assert rel.description is None
    assert rel.embedding is None


def test_property_optional_defaults():
    """Test that optional fields have correct defaults."""
    prop = Property(id="p1", name="email")
    assert prop.type is None
    assert prop.description is None
    assert prop.unique is False
    assert prop.nullable is True
    assert prop.indexed is False
    assert prop.existence is False
    assert prop.embedding is None
