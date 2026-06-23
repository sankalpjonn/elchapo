"""Integration tests for POST /c (create) against mocked DynamoDB."""
import time

import models

SECRET = "DCCOMICS"  # matches conftest staging SECRET_KEY


def _post(client, path, **over):
    body = {
        "path": path,
        "redirect_url": "https://dest.test/landing",
        "webhook": None,
        "secret_key": SECRET,
    }
    body.update(over)
    return client.post("/c", json=body)


def test_create_inserts_into_v2_and_returns_200(client):
    resp = _post(client, "brand-abc123")
    assert resp.status_code == 200
    item = models.ShortURLV2.get("brand-abc123")
    assert item.redirection_url == "https://dest.test/landing"


def test_create_does_not_write_to_v1(client):
    _post(client, "brand-abc123")
    assert not list(models.ShortURL.query("brand-abc123"))


def test_create_sets_expires_at_about_ttl_out_in_seconds(client):
    _post(client, "brand-abc123")
    item = models.ShortURLV2.get("brand-abc123")
    now = int(time.time())
    # ~90 days in seconds, with generous slack; and unmistakably seconds not ms.
    assert (now + 89 * 86400) < item.expires_at < (now + 91 * 86400)


def test_create_duplicate_in_v2_returns_409(client):
    _post(client, "brand-abc123")
    resp = _post(client, "brand-abc123", redirect_url="https://other.test")
    assert resp.status_code == 409
    # original mapping must be untouched (no clobber)
    assert models.ShortURLV2.get("brand-abc123").redirection_url == "https://dest.test/landing"


def test_create_collision_with_legacy_v1_path_returns_409(client):
    # grace-period guard: a new path must not hijack a still-live legacy path
    models.ShortURL(url="brand-legacy", redirection_url="https://old.test").save()
    resp = _post(client, "brand-legacy", redirect_url="https://new.test")
    assert resp.status_code == 409
    assert not list(models.ShortURLV2.query("brand-legacy"))  # not copied/written


def test_create_wrong_secret_returns_403(client):
    resp = _post(client, "brand-abc123", secret_key="WRONG")
    assert resp.status_code == 403
