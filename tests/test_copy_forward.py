"""Tests for the copy-forward mapping from a v1 row to a v2 row."""
from datetime import datetime

import pytz

import app
import constants
import models
import utils


def test_preserves_created_at_and_core_fields():
    created = datetime(2024, 1, 1, tzinfo=pytz.UTC)
    v1 = models.ShortURL(
        url="abc", redirection_url="https://x.test", webhook="https://h.test",
        created_at=created,
    )
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)

    v2 = app.build_v2_from_v1(v1, now)

    assert v2.url == "abc"
    assert v2.redirection_url == "https://x.test"
    assert v2.webhook == "https://h.test"
    assert v2.created_at == created  # preserved, NOT reset to now


def test_expires_at_is_now_plus_ttl_in_seconds_not_created_plus_ttl():
    created = datetime(2024, 1, 1, tzinfo=pytz.UTC)
    v1 = models.ShortURL(url="abc", redirection_url="https://x.test", created_at=created)
    now = datetime(2026, 6, 22, tzinfo=pytz.UTC)

    v2 = app.build_v2_from_v1(v1, now)

    assert v2.expires_at == utils.ttl_epoch_seconds(now, constants.TTL_DAYS)
    # A 2-year-old link must NOT get created_at + TTL (already expired -> vanish).
    assert v2.expires_at != utils.ttl_epoch_seconds(created, constants.TTL_DAYS)
