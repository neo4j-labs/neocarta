"""Shared enum types for the semantic graph schema."""

from enum import Enum


class NodeLabel(str, Enum):
    """Node labels for the semantic graph."""

    DATABASE = "Database"
    SCHEMA = "Schema"
    TABLE = "Table"
    COLUMN = "Column"
    VALUE = "Value"
    GLOSSARY = "Glossary"
    CATEGORY = "Category"
    BUSINESS_TERM = "BusinessTerm"
    QUERY = "Query"
    CTE = "CTE"
    DOMAIN = "Domain"
    OSI_SEMANTIC_MODEL = "OsiSemanticModel"
    OSI_TABLE = "OsiTable"
    OSI_COLUMN = "OsiColumn"
    METRIC = "Metric"
    JOIN = "Join"
    EXPRESSION = "Expression"
    ASPECT = "Aspect"
    OSI_AI_CONTEXT = "OsiAiContext"
    OSI_CUSTOM_EXTENSIONS = "OsiCustomExtensions"
    NEOCARTA_GRAPH = "__neocarta_graph__"

    def __str__(self) -> str:
        """Return the enum value as a plain string."""
        return self.value

    def __format__(self, format_spec: str) -> str:
        """Format the enum value, ensuring consistent behaviour across Python versions."""
        return self.value.__format__(format_spec)


class RelationshipType(str, Enum):
    """Relationship types for the semantic graph."""

    HAS_SCHEMA = "HAS_SCHEMA"
    HAS_TABLE = "HAS_TABLE"
    HAS_COLUMN = "HAS_COLUMN"
    HAS_VALUE = "HAS_VALUE"
    HAS_CATEGORY = "HAS_CATEGORY"
    HAS_BUSINESS_TERM = "HAS_BUSINESS_TERM"
    REFERENCES = "REFERENCES"
    TAGGED_WITH = "TAGGED_WITH"
    USES_TABLE = "USES_TABLE"
    USES_COLUMN = "USES_COLUMN"
    DEFINES = "DEFINES"
    HAS_QUERY = "HAS_QUERY"
    HAS_METRIC = "HAS_METRIC"
    HAS_ASPECT = "HAS_ASPECT"
    HAS_EXPRESSION = "HAS_EXPRESSION"
    HAS_SOURCE_TABLE = "HAS_SOURCE_TABLE"
    HAS_TARGET_TABLE = "HAS_TARGET_TABLE"
    USED_IN_JOIN = "USED_IN_JOIN"

    def __str__(self) -> str:
        """Return the enum value as a plain string."""
        return self.value

    def __format__(self, format_spec: str) -> str:
        """Format the enum value, ensuring consistent behaviour across Python versions."""
        return self.value.__format__(format_spec)
