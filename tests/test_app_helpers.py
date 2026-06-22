"""Unit tests for the pure helpers in app.py (no DynamoDB / network)."""
import app


def test_get_hook_appends_path_as_query_when_no_existing_query():
    assert app.get_hook("https://hook.example.com/cb", "abc") == \
        "https://hook.example.com/cb?path=abc"


def test_get_hook_appends_path_with_ampersand_when_query_exists():
    assert app.get_hook("https://hook.example.com/cb?id=1", "abc") == \
        "https://hook.example.com/cb?id=1&path=abc"


def test_get_hook_returns_none_when_no_webhook():
    assert app.get_hook(None, "abc") is None
