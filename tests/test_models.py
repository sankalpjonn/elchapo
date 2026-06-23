"""
Tests for the DynamoDB models.

Importing `models` must have NO AWS side effects (the old import-time
create_table is removed), so this file importing at all is part of the test.
"""
import models


def test_v1_table_name_is_env_scoped():
    assert models.ShortURL.Meta.table_name == "staging-el-chapo-short-url-store"


def test_v2_table_name_has_v2_suffix():
    assert models.ShortURLV2.Meta.table_name == "staging-el-chapo-short-url-store-v2"


def test_v2_has_expires_at_attribute():
    assert hasattr(models.ShortURLV2, "expires_at")


def test_v2_carries_the_core_link_fields():
    for field in ("url", "redirection_url", "webhook", "created_at"):
        assert hasattr(models.ShortURLV2, field)


def test_v2_created_at_default_is_callable_not_frozen():
    # Must be the function (evaluated per-write), not a value frozen at import.
    assert callable(models.ShortURLV2.created_at.default)


def test_v1_created_at_default_is_callable_not_frozen():
    assert callable(models.ShortURL.created_at.default)
