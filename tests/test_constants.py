"""Tests for config constants (TTL window + env-scoped metric namespace)."""
import constants


def test_metric_namespace_is_environment_scoped():
    # conftest sets ENVIRONMENT=staging, so the namespace must differentiate it.
    assert constants.METRIC_NAMESPACE == "Elchapo/staging"


def test_metric_name_is_active_link_age_days():
    assert constants.METRIC_NAME == "ActiveLinkAgeDays"


def test_default_ttl_is_90_days():
    assert constants.TTL_DAYS == 90
