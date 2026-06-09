"""Shared Collibra type-resolution helpers used by both sub-connector extractors.

Collibra identifies asset/domain/relation *types* by UUID, but its operating
model is configured with human display names. The extractors discover the
UUID→name maps once per run (``CollibraClient.discover_types``) and use a
:class:`CollibraTypeResolver` to classify each entity into a neocarta type via
the alias tables in :mod:`neocarta.connectors.collibra.type_mapping`.
"""

from .type_mapping import ASSET_TYPE_ALIASES, DOMAIN_TYPE_ALIASES, RELATION_TYPE_ALIASES

_DEFAULT_DOMAIN_TYPE = "Schema"


class CollibraTypeResolver:
    """Classify Collibra asset/domain/relation types into neocarta types.

    Parameters
    ----------
    asset_types : dict[str, str]
        UUID → display-name map for asset types.
    domain_types : dict[str, str]
        UUID → display-name map for domain types.
    relation_types : dict[str, str]
        UUID → display-name map for relation types.
    """

    def __init__(
        self,
        asset_types: dict[str, str],
        domain_types: dict[str, str],
        relation_types: dict[str, str],
    ) -> None:
        """Build forward and reverse (lower-name → UUID) type maps."""
        self.asset_types = asset_types
        self.domain_types = domain_types
        self.relation_types = relation_types
        self._asset_type_by_name = {v.lower(): k for k, v in asset_types.items()}

    def neocarta_asset_type(self, asset_type_name: str) -> str | None:
        """Return the neocarta node type for a Collibra asset type, or ``None`` if unmapped."""
        return ASSET_TYPE_ALIASES.get(asset_type_name.lower())

    def neocarta_domain_type(self, domain_type_name: str) -> str:
        """Return ``"Schema"`` or ``"Glossary"`` for a Collibra domain type."""
        return DOMAIN_TYPE_ALIASES.get(domain_type_name.lower(), _DEFAULT_DOMAIN_TYPE)

    def neocarta_relation(self, relation_type_name: str) -> str | None:
        """Return the neocarta relationship for a Collibra relation type, or ``None``."""
        return RELATION_TYPE_ALIASES.get(relation_type_name.lower())

    def asset_type_ids_for_names(self, names: list[str]) -> list[str]:
        """Resolve asset-type display names (case-insensitive) to their UUIDs."""
        return [
            self._asset_type_by_name[n.lower()]
            for n in names
            if n.lower() in self._asset_type_by_name
        ]

    def relation_type_ids_for_neocarta(self, neocarta_relationships: set[str]) -> list[str]:
        """Resolve the relation-type UUIDs whose alias maps into ``neocarta_relationships``."""
        return [
            uuid
            for uuid, name in self.relation_types.items()
            if self.neocarta_relation(name) in neocarta_relationships
        ]
