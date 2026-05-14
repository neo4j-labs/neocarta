"""Pydantic models for Collibra Core REST API v2 response payloads."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CollibraPagedResponse(BaseModel, Generic[T]):
    """Generic paged response from Collibra list endpoints."""

    total: int = Field(..., description="Total number of results across all pages")
    offset: int = Field(..., description="Current page offset")
    limit: int = Field(..., description="Page size requested")
    results: list[Any] = Field(default_factory=list, description="Results for this page")


class CollibraTypeRef(BaseModel):
    """A typed reference (id + name) used throughout Collibra responses."""

    id: str = Field(..., description="UUID of the type")
    name: str = Field(..., description="Display name of the type")


class CollibraStatus(BaseModel):
    """Asset governance status."""

    id: str = Field(..., description="UUID of the status")
    name: str = Field(..., description="Status display name (e.g. Accepted, Draft, Deprecated)")


class CollibraCommunity(BaseModel):
    """A Collibra Community (top-level container)."""

    id: str = Field(..., description="UUID of the community")
    name: str = Field(..., description="Display name of the community")
    description: str | None = Field(default=None, description="Community description")


class CollibraDomain(BaseModel):
    """A Collibra Domain (belongs to a Community)."""

    id: str = Field(..., description="UUID of the domain")
    name: str = Field(..., description="Display name of the domain")
    description: str | None = Field(default=None, description="Domain description")
    community: CollibraTypeRef = Field(..., description="Parent community reference")
    type: CollibraTypeRef = Field(..., description="Domain type reference")


class CollibraAsset(BaseModel):
    """A Collibra Asset (belongs to a Domain)."""

    id: str = Field(..., description="UUID of the asset")
    name: str = Field(..., description="Display name of the asset")
    display_name: str | None = Field(
        default=None, alias="displayName", description="Human-readable display name"
    )
    domain: CollibraTypeRef = Field(..., description="Parent domain reference")
    type: CollibraTypeRef = Field(..., description="Asset type reference")
    status: CollibraStatus | None = Field(default=None, description="Governance status")


class CollibraAttribute(BaseModel):
    """A Collibra Attribute (key-value property of an Asset)."""

    id: str = Field(..., description="UUID of the attribute")
    asset: CollibraTypeRef = Field(..., description="Parent asset reference")
    type: CollibraTypeRef = Field(..., description="Attribute type reference (e.g. Description)")
    value: str | None = Field(default=None, description="String value of the attribute")


class CollibraRelation(BaseModel):
    """A Collibra Relation between two Assets."""

    id: str = Field(..., description="UUID of the relation")
    source: CollibraTypeRef = Field(..., description="Source asset reference")
    target: CollibraTypeRef = Field(..., description="Target asset reference")
    type: CollibraTypeRef = Field(..., description="Relation type reference")


class CollibraLineageNode(BaseModel):
    """An outbound lineage target from the Catalog Technical Lineage API."""

    id: str = Field(..., description="UUID of the target asset")
    name: str = Field(..., description="Display name of the target asset")
    type: str | None = Field(default=None, description="Lineage node type (TABLE or COLUMN)")


class CollibraAssetType(BaseModel):
    """An asset type from GET /rest/2.0/assetTypes."""

    id: str = Field(..., description="UUID of the asset type")
    name: str = Field(..., description="Display name of the asset type")


class CollibraDomainType(BaseModel):
    """A domain type from GET /rest/2.0/domainTypes."""

    id: str = Field(..., description="UUID of the domain type")
    name: str = Field(..., description="Display name of the domain type")


class CollibraRelationType(BaseModel):
    """A relation type from GET /rest/2.0/relationTypes."""

    id: str = Field(..., description="UUID of the relation type")
    name: str = Field(..., description="Display name of the relation type")
