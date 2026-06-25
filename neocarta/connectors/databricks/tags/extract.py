"""Extract Databricks governed-tag definitions via the Databricks SDK.

Reads governed-tag *definitions* (tag policies) from a Databricks workspace using
``WorkspaceClient.tag_policies.list_tag_policies()`` — no SQL warehouse, no
``information_schema``. Governed tags are account-level controlled vocabularies:
a ``tag_key`` with an optional description and an optional list of allowed
``values``.

The connector reads only the *definition* layer here; tag *assignments*
(``information_schema.*_tags`` → ``TAGGED_WITH`` edges to columns/tables/schemas)
need a SQL warehouse and are a planned follow-up. The extractor does not import
the Databricks SDK at module load — it operates on the injected
``WorkspaceClient`` by duck typing, so importing this connector does not require
the optional ``[databricks]`` extra until a client is actually built.
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import pandas as pd

from ...._logging import log_stage
from ....errors import AuthError, ConnectorError, NeocartaError
from ....warnings import DatabricksTagsWarning
from .models import TagPolicyValueInfo

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# Governed tags whose key starts with one of these namespaces are
# platform/partner-managed (auto-applied) rather than user-authored governance
# vocabulary, so they are excluded by default. Observed populators:
#   system.*  — platform system tags (e.g. system.certification_status)
#   class.*   — auto-applied data-classification tags
#   ai.*      — auto-applied to system.ai models (e.g. ai.model_family/creator)
#   sap.*     — SAP Delta Sharing governance tags
# Override the set via the ``system_prefixes`` argument (CLI: --system-prefixes);
# pass include_system_tags=True to ingest everything regardless of prefix.
DEFAULT_SYSTEM_PREFIXES: tuple[str, ...] = ("system.", "class.", "ai.", "sap.")

_CACHE_COLS = ["tag_key", "tag_description", "tag_policy_id", "value_name"]


class DatabricksTagsExtractor:
    """Extractor for Databricks governed-tag definitions.

    Owns no client of its own — it operates on an injected
    :class:`databricks.sdk.WorkspaceClient`. Internal cached state is *not* part
    of the public API; callers interact only through the connector's stage
    methods and read results via the :attr:`tag_key_info` / :attr:`tag_value_info`
    properties.

    Parameters
    ----------
    workspace_client : databricks.sdk.WorkspaceClient
        An authenticated Databricks workspace client.
    source : str | None, default None
        Explicit namespace for the governance-tag node ids. Governed tags are
        account-level, so ids are scoped by a source identifier to avoid
        collisions across accounts/vendors. When ``None`` the namespace is
        derived from the workspace's metastore id (falling back to the host).
    system_prefixes : tuple[str, ...] | None, default None
        Tag-key prefixes treated as platform/system tags and excluded unless
        ``include_system_tags=True``. When ``None`` the
        :data:`DEFAULT_SYSTEM_PREFIXES` set (``system.``/``class.``/``ai.``/``sap.``)
        is used. Pass an empty tuple to disable prefix-based filtering.
    """

    def __init__(
        self,
        workspace_client: WorkspaceClient,
        *,
        source: str | None = None,
        system_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the extractor with an injected workspace client."""
        self.workspace_client = workspace_client
        self._source_override = source
        self._system_prefixes: tuple[str, ...] = (
            tuple(system_prefixes) if system_prefixes is not None else DEFAULT_SYSTEM_PREFIXES
        )

        self._tag_policy_info: pd.DataFrame = pd.DataFrame(columns=_CACHE_COLS)
        self._source: str | None = None

    @property
    def source(self) -> str | None:
        """The resolved namespace for governance-tag node ids (metastore id / host)."""
        return self._source

    @property
    def tag_key_info(self) -> pd.DataFrame:
        """One row per governed tag key (becomes a :GovernanceTagKey)."""
        cols = ["source", "tag_key", "tag_description", "tag_policy_id"]
        if self._tag_policy_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._tag_policy_info.drop_duplicates(subset=["tag_key"]).copy()
        df["source"] = self._source
        return df[cols]

    @property
    def tag_value_info(self) -> pd.DataFrame:
        """One row per (governed tag key, allowed value) — becomes a :GovernanceTagValue.

        Value-less governed tags carry ``value_name=None`` and are dropped here, so
        they yield a :GovernanceTagKey with no :GovernanceTagValue options.
        """
        cols = ["source", "tag_key", "value_name"]
        if self._tag_policy_info.empty:
            return pd.DataFrame(columns=cols)
        df = self._tag_policy_info[self._tag_policy_info["value_name"].notna()]
        df = df.drop_duplicates(subset=["tag_key", "value_name"]).copy()
        if df.empty:
            return pd.DataFrame(columns=cols)
        df["source"] = self._source
        return df[cols]

    @log_stage(count=False)
    def extract(self, *, include_system_tags: bool = False) -> None:
        """Resolve the id namespace and read governed-tag definitions.

        Parameters
        ----------
        include_system_tags : bool, default False
            Whether to include platform-managed governed tags — those whose key
            matches one of the configured ``system_prefixes`` (default
            ``system.``/``class.``/``ai.``/``sap.``). Excluded by default.
        """
        self._resolve_source()
        self.extract_tag_policies(include_system_tags=include_system_tags)

    @log_stage
    def extract_tag_policies(self, *, include_system_tags: bool = False) -> pd.DataFrame:
        """List governed-tag definitions and flatten them to one row per value.

        Returns:
        -------
        pd.DataFrame
            One row per (tag_key, allowed value); a value-less tag yields one row
            with ``value_name=None``. Cached on the instance and projected via
            :attr:`tag_key_info` / :attr:`tag_value_info`.
        """
        records: list[TagPolicyValueInfo] = []
        try:
            for policy in self.workspace_client.tag_policies.list_tag_policies():
                tag_key = policy.tag_key
                if not tag_key:
                    # A policy with no key is malformed and cannot be modelled; skip it
                    # rather than let ``.startswith`` raise and masquerade as a listing failure.
                    continue
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

    def _resolve_source(self) -> None:
        """Determine the namespace for governance-tag node ids.

        Priority: explicit override → workspace metastore id → workspace host
        (with a :class:`DatabricksTagsWarning`, since governed tags are
        account-level and a host-derived namespace is workspace-scoped).
        """
        if self._source_override:
            self._source = self._source_override
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
            self._source = metastore_id
            return

        host = getattr(getattr(self.workspace_client, "config", None), "host", None) or "databricks"
        self._source = host
        warnings.warn(
            DatabricksTagsWarning(
                "Could not determine the Databricks metastore id; deriving the governance-tag "
                "id namespace from the workspace host instead. Pass source=... to set it explicitly."
            ),
            stacklevel=2,
        )

    def _is_system_tag(self, tag_key: str) -> bool:
        """Whether a governed tag key is platform-managed (matches a configured prefix)."""
        return any(tag_key.startswith(prefix) for prefix in self._system_prefixes)

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
