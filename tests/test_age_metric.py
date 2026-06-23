"""
Tests for the ActiveLinkAgeDays metric payload builder.

The cost guarantee lives here: value-only, NO dimensions, and an env-scoped
namespace so staging vs production are separated by namespace alone.
"""
from datetime import datetime, timedelta

import pytz

import app


def _created(now=None):
    return datetime(2026, 1, 1, tzinfo=pytz.UTC)


def test_value_is_age_in_days():
    created = _created()
    now = created + timedelta(days=10)
    payload = app.build_age_metric(created, now)
    assert payload["MetricData"][0]["Value"] == 10.0


def test_namespace_is_env_scoped():
    created = _created()
    payload = app.build_age_metric(created, created)
    assert payload["Namespace"] == "Elchapo/staging"


def test_metric_name_is_active_link_age_days():
    created = _created()
    payload = app.build_age_metric(created, created)
    assert payload["MetricData"][0]["MetricName"] == "ActiveLinkAgeDays"


def test_has_no_dimensions_cost_guard():
    created = _created()
    payload = app.build_age_metric(created, created)
    assert "Dimensions" not in payload["MetricData"][0]
