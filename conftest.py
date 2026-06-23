"""
Pytest config for the elchapo test suite.

Set environment BEFORE any app module (constants.py reads env at import time).
Default to the *staging* identity so tests exercise the staging metric namespace,
and inject fake AWS creds so moto/botocore can never touch real AWS.
"""
import os

os.environ.setdefault("ENVIRONMENT", "staging")
os.environ.setdefault("SECRET_KEY", "DCCOMICS")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

import pytest


@pytest.fixture
def aws_backend():
    """A fresh mocked DynamoDB + CloudWatch with both link tables created."""
    from moto import mock_aws
    with mock_aws():
        import models
        models.ShortURL.create_table(billing_mode="PAY_PER_REQUEST", wait=True)
        models.ShortURLV2.create_table(billing_mode="PAY_PER_REQUEST", wait=True)
        yield


@pytest.fixture
def aws_empty():
    """Mocked AWS with NO tables pre-created (for the table-provisioning script)."""
    from moto import mock_aws
    with mock_aws():
        yield


@pytest.fixture
def webhook_calls(monkeypatch):
    """Capture (instead of actually firing) webhook calls made on redirect."""
    import app
    calls = []
    monkeypatch.setattr(app, "call_url", lambda url: calls.append(url))
    return calls


@pytest.fixture
def client(aws_backend, webhook_calls):
    import app
    app.app.config.update(TESTING=True)
    return app.app.test_client()
