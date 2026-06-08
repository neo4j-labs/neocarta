"""Type mapping aliases for Collibra asset, domain, and relation types.

Collibra type names are customer-configurable. These synonym maps cover the
standard out-of-the-box operating model. Users can override via constructor
parameters. All lookups are case-insensitive (normalise to lower before lookup).
"""

# Maps lowercase Collibra asset type display-name synonyms → neocarta target type tag.
# The transformer resolves UUIDs to display names at startup, then uses these aliases.
ASSET_TYPE_ALIASES: dict[str, str] = {
    "table": "Table",
    "data set": "Table",
    "dataset": "Table",
    "database view": "Table",
    "view": "Table",
    "column": "Column",
    "field": "Column",
    "report attribute": "Column",
    "report field": "Column",
    "business term": "BusinessTerm",
    "data category": "Category",
    "data domain": "Category",
    "sub domain": "Category",
    "subdomain": "Category",
}

# Maps lowercase Collibra domain type display-name synonyms → neocarta node class tag.
DOMAIN_TYPE_ALIASES: dict[str, str] = {
    "physical data dictionary": "Schema",
    "physical data model": "Schema",
    "data asset catalog": "Schema",
    "business glossary": "Glossary",
    "business terminology": "Glossary",
    "policy glossary": "Glossary",
    "reference data": "Glossary",
}

# Maps lowercase Collibra relation type display-name synonyms → neocarta relationship tag.
RELATION_TYPE_ALIASES: dict[str, str] = {
    "asset contains column": "HAS_COLUMN",
    "table contains column": "HAS_COLUMN",
    "view contains column": "HAS_COLUMN",
    "data attribute / data element / business term association": "TAGGED_WITH",
    "asset associated with business term": "TAGGED_WITH",
    "business term association": "TAGGED_WITH",
    "domain / sub domain": "HAS_CATEGORY",
    "category / business term": "HAS_BUSINESS_TERM",
    "glossary / business term": "HAS_BUSINESS_TERM",
}
