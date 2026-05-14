"""Pytest fixtures with synthetic Salesforce sobject describe data.

All data is entirely synthetic — no real org names, credentials, or proprietary
field/object definitions are used.
"""

import pytest

# ── Synthetic sobject describe fixtures ──────────────────────────────────────


@pytest.fixture
def account_object():
    """Minimal synthetic Account (standard object)."""
    return {
        "name": "Account",
        "label": "Account",
        "labelPlural": "Accounts",
        "keyPrefix": "001",
        "custom": False,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": False,
        "fields": [
            {
                "name": "Id",
                "label": "Account ID",
                "type": "id",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": True,
                "referenceTo": [],
                "picklistValues": [],
            },
            {
                "name": "Name",
                "label": "Account Name",
                "type": "string",
                "length": 255,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": False,
                "referenceTo": [],
                "picklistValues": [],
            },
            {
                "name": "Industry",
                "label": "Industry",
                "type": "picklist",
                "length": 40,
                "precision": 0,
                "scale": 0,
                "nillable": True,
                "unique": False,
                "idLookup": False,
                "referenceTo": [],
                "picklistValues": [
                    {"value": "Technology", "active": True},
                    {"value": "Finance", "active": True},
                    {"value": "Healthcare", "active": False},
                ],
            },
        ],
    }


@pytest.fixture
def contact_object():
    """Minimal synthetic Contact (standard object, with FK to Account)."""
    return {
        "name": "Contact",
        "label": "Contact",
        "labelPlural": "Contacts",
        "keyPrefix": "003",
        "custom": False,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": True,
        "fields": [
            {
                "name": "Id",
                "label": "Contact ID",
                "type": "id",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": True,
                "referenceTo": [],
                "picklistValues": [],
            },
            {
                "name": "AccountId",
                "label": "Account ID",
                "type": "reference",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": True,
                "unique": False,
                "idLookup": False,
                "referenceTo": ["Account"],
                "picklistValues": [],
            },
            {
                "name": "OwnerId",
                "label": "Owner ID",
                "type": "reference",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": False,
                "referenceTo": ["User"],
                "picklistValues": [],
            },
        ],
    }


@pytest.fixture
def managed_package_object():
    """Synthetic managed-package object (Acme namespace)."""
    return {
        "name": "Acme__Widget__c",
        "label": "Widget",
        "labelPlural": "Widgets",
        "keyPrefix": "a0B",
        "custom": True,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": True,
        "fields": [
            {
                "name": "Id",
                "label": "Record ID",
                "type": "id",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": True,
                "referenceTo": [],
                "picklistValues": [],
            },
            {
                "name": "Acme__Status__c",
                "label": "Status",
                "type": "picklist",
                "length": 255,
                "precision": 0,
                "scale": 0,
                "nillable": True,
                "unique": False,
                "idLookup": False,
                "referenceTo": [],
                "picklistValues": [
                    {"value": "Active", "active": True},
                    {"value": "Inactive", "active": True},
                ],
            },
        ],
    }


@pytest.fixture
def unmanaged_custom_object():
    """Synthetic unmanaged custom object (no namespace prefix)."""
    return {
        "name": "Project__c",
        "label": "Project",
        "labelPlural": "Projects",
        "keyPrefix": "a0C",
        "custom": True,
        "queryable": True,
        "createable": True,
        "updateable": True,
        "deletable": True,
        "fields": [
            {
                "name": "Id",
                "label": "Record ID",
                "type": "id",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": False,
                "unique": False,
                "idLookup": True,
                "referenceTo": [],
                "picklistValues": [],
            },
            {
                "name": "AccountId__c",
                "label": "Account",
                "type": "reference",
                "length": 18,
                "precision": 0,
                "scale": 0,
                "nillable": True,
                "unique": False,
                "idLookup": False,
                "referenceTo": ["Account"],
                "picklistValues": [],
            },
        ],
    }


@pytest.fixture
def all_objects(account_object, contact_object, managed_package_object, unmanaged_custom_object):
    """All four synthetic objects together."""
    return [account_object, contact_object, managed_package_object, unmanaged_custom_object]


ORG_NAME = "test-org"
