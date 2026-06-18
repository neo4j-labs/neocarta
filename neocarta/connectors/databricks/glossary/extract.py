"""Extract Databricks governed-tag definitions via the Databricks SDK.

Reads governed-tag *definitions* (tag policies) from a Databricks workspace using
``WorkspaceClient.tag_policies.list_tag_policies()`` — no SQL warehouse, no
``information_schema``. Governed tags are account-level controlled vocabularies:
a ``tag_key`` with an optional description and an optional list of allowed
``values``.

The connector reads only definitions in v1; tag *assignments*
(``information_schema.*_tags`` → ``TAGGED_WITH`` edges) are a planned follow-up.
The extractor does not import the Databricks SDK at module load — it operates on
the injected ``WorkspaceClient`` by duck typing, so importing this connector does
not require the optional ``[databricks]`` extra until a client is actually built.
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import pandas as pd

from ...._logging import log_stage
from ....errors import AuthError, ConnectorError, NeocartaError
from ....warnings import DatabricksGlossaryWarning
from .models import TagPolicyValueInfo

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# Governed tags whose key is namespaced under "system." are platform-managed
# (e.g. system.certification_status) rather than user-authored business
# vocabulary, so they are excluded unless include_system_tags=True.
_SYSTEM_TAG_PREFIX = "system."

_CACHE_COLS = ["tag_key", "tag_description", "tag_policy_id", "value_name"]


class DatabricksGlossaryExtractor:
    """Extractor for Databricks governed-tag definitions.

    Owns no client of its own — it operates on an injected
    :class:`databricks.sdk.WorkspaceClient`. Internal cached state is *not* part
    of the public API; callers interact only through the connector's stage
    methods and read results via the :attr:`glossary_info` / :attr:`category_info`
    / :attr:`business_term_info` properties.

    Parameters
    ----------
    workspace_client : databricks.sdk.WorkspaceClient
        An authenticated Databricks workspace client.
    glossary_id : str | None, default None
        Explicit id for the synthesized account-level ``Glossary`` node. When
        ``None`` the id is derived from the workspace's metastore id (falling back
        to the workspace host).
    glossary_name : str, default "Unity Catalog Governed Tags"
        Display name for the synthesized ``Glossary`` node.
    """

    def __init__(
        self,
        workspace_client: WorkspaceClient,
        *,
        glossary_id: str | None = None,
        glossary_name: str = "Unity Catalog Governed Tags",
    ) -> None:
        """Initialize the extractor with an injected workspace client."""
        self.workspace_client = workspace_client
        self._glossary_id_override = glossary_id
        self._glossary_name = glossary_name

        self._tag_policy_info: pd.DataFrame = pd.DataFrame(columns=_CACHE_COLS)
        self._glossary_raw_id: str | None = None
        self._glossary_resource_path: str | None = None

    @property
    def glossary_info(self) -> pd.DataFrame:
        """One-row DataFrame describing the synthesized account-level glossary."""
        cols = ["glossary_id", "glossary_name", "glossary_resource_path"]
        if self._glossary_raw_id is None:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame(
            [
                {
                    "glossary_id": self._glossary_raw_id,
                    "glossary_name": self._glossary_name,
                    "glossary_resource_path": self._glossary_resource_path,
                }
            ],
            columns=cols,
        )

    @property
    def category_info(self) -> pd.DataFrame:
        """One row per governed tag key (becomes a :Category)."""
        cols = ["glossary_id", "tag_key", "tag_description", "tag_policy_id"]
        if self._tag_policy_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._tag_policy_info.drop_duplicates(subset=["tag_key"]).copy()
        df["glossary_id"] = self._glossary_raw_id
        return df[cols]

    @property
    def business_term_info(self) -> pd.DataFrame:
        """One row per (governed tag key, allowed value) — becomes a :BusinessTerm.

        Value-less governed tags carry ``value_name=None`` and are dropped here, so
        they yield a :Category with no :BusinessTerm children.
        """
        cols = ["glossary_id", "tag_key", "value_name"]
        if self._tag_policy_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._tag_policy_info[self._tag_policy_info["value_name"].notna()]
        df = df.drop_duplicates(subset=["tag_key", "value_name"]).copy()
        if df.empty:
            return pd.DataFrame(columns=cols)
        df["glossary_id"] = self._glossary_raw_id
        return df[cols]

    @log_stage(count=False)
    def extract(self, *, include_system_tags: bool = False) -> None:
        """Resolve the glossary identity and read governed-tag definitions.

        Parameters
        ----------
        include_system_tags : bool, default False
            Whether to include platform-managed ``system.*`` governed tags
            (e.g. ``system.certification_status``). Excluded by default.
        """
        self._resolve_glossary_identity()
        self.extract_tag_policies(include_system_tags=include_system_tags)

    @log_stage
    def extract_tag_policies(self, *, include_system_tags: bool = False) -> pd.DataFrame:
        """List governed-tag definitions and flatten them to one row per value.

        Returns:
        -------
        pd.DataFrame
            One row per (tag_key, allowed value); a value-less tag yields one row
            with ``value_name=None``. Cached on the instance and projected via
            :attr:`category_info` / :attr:`business_term_info`.
        """
        records: list[TagPolicyValueInfo] = []
        try:
            for policy in self.workspace_client.tag_policies.list_tag_policies():
                tag_key = policy.tag_key
                if not include_system_tags and self._is_system_tag(tag_key):
                    continue
                description = policy.description or None
                policy_id = policy.id
                values = policy.values or []
                if not values:
                    records.append(
                        TagPolicyValueInfo(
                            tag_key=tag_key,
                            tag_description=description,
                            tag_policy_id=policy_id,
                            value_name=None,
                        )
                    )
                    continue
                for value in values:
                    records.append(
                        TagPolicyValueInfo(
                            tag_key=tag_key,
                            tag_description=description,
                            tag_policy_id=policy_id,
                            value_name=value.name,
                        )
                    )
        except Exception as exc:
            raise self._wrap_sdk_error(exc) from exc

        df = pd.DataFrame(records, columns=_CACHE_COLS)
        self._tag_policy_info = df
        return df

    def _resolve_glossary_identity(self) -> None:
        """Determine the synthesized glossary's id + resource path.

        Priority: explicit override → workspace metastore id → workspace host
        (with a :class:`DatabricksGlossaryWarning`, since governed tags are
        account-level and a host-derived id is workspace-scoped).
        """
        if self._glossary_id_override:
            self._glossary_raw_id = self._glossary_id_override
            self._glossary_resource_path = self._glossary_id_override
            return

        metastore_id = None
        try:
            summary = self.workspace_client.metastores.summary()
            metastore_id = getattr(summary, "global_metastore_id", None) or getattr(
                summary, "metastore_id", None
            )
        except Exception as exc:
            logger.warning("Could not read Databricks metastore id (%s)", type(exc).__name__)

        if metastore_id:
            self._glossary_raw_id = metastore_id
            self._glossary_resource_path = metastore_id
            return

        host = getattr(getattr(self.workspace_client, "config", None), "host", None) or "databricks"
        self._glossary_raw_id = host
        self._glossary_resource_path = host
        warnings.warn(
            DatabricksGlossaryWarning(
                "Could not determine the Databricks metastore id; deriving the Glossary id "
                "from the workspace host instead. Pass glossary_id=... to set it explicitly."
            ),
            stacklevel=2,
        )

    @staticmethod
    def _is_system_tag(tag_key: str) -> bool:
        """Whether a governed tag key is platform-managed (``system.*``)."""
        return tag_key.startswith(_SYSTEM_TAG_PREFIX)

    @staticmethod
    def _wrap_sdk_error(exc: Exception) -> NeocartaError:
        """Map a Databricks SDK failure to a typed neocarta error.

        Authentication / permission failures become :class:`AuthError`; anything
        else becomes :class:`ConnectorError`. Only the exception *type* is
        recorded — never the message, which may echo request detail.
        """
        auth_types: tuple[type[Exception], ...] = ()
        try:
            from databricks.sdk.errors import (  # noqa: PLC0415
                PermissionDenied,
                Unauthenticated,
            )

            auth_types = (Unauthenticated, PermissionDenied)
        except Exception:
            pass

        if auth_types and isinstance(exc, auth_types):
            return AuthError(
                "Databricks rejected the request while listing governed tag policies.",
                suggestion="Check the workspace token and that it can read tag policies.",
                details={"error_type": type(exc).__name__},
            )
        return ConnectorError(
            "Could not list Databricks governed tag policies.",
            details={"error_type": type(exc).__name__},
        )
