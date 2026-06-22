"""Unit tests for time/TTL helpers in utils.py."""
from datetime import datetime

import pytz

import utils


def test_ttl_epoch_seconds_equals_posix_seconds_for_zero_days():
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)
    assert utils.ttl_epoch_seconds(now, days=0) == int(now.timestamp())


def test_ttl_epoch_seconds_adds_days_in_seconds():
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)
    assert utils.ttl_epoch_seconds(now, days=90) == int(now.timestamp()) + 90 * 86400


def test_ttl_epoch_seconds_is_seconds_not_milliseconds():
    # 2026 in epoch SECONDS is ~1.7e9; a milliseconds bug would land at ~1.7e12.
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)
    assert 1_000_000_000 < utils.ttl_epoch_seconds(now, days=90) < 10_000_000_000
