"""Tests for the TTL canary / deletion-metric helper."""
from datetime import datetime

import pytz

from ops import check_ttl


def test_build_canary_has_fixed_key_and_past_expiry():
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)
    canary = check_ttl.build_canary(now)
    assert canary.url == check_ttl.CANARY_KEY
    # already expired so DynamoDB TTL is eligible to reap it
    assert int(canary.expires_at) < int(now.timestamp())
    assert canary.redirection_url  # a placeholder destination is set


def test_summarize_ttl_metric_sums_datapoints():
    assert check_ttl.summarize_ttl_metric([{"Sum": 1.0}, {"Sum": 4.0}]) == 5.0


def test_summarize_ttl_metric_empty_is_zero():
    assert check_ttl.summarize_ttl_metric([]) == 0
