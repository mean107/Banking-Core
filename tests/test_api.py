import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ROLE", "api")
    redis = SimpleNamespace(
        getdel=AsyncMock(
            return_value=json.dumps({"status": 200, "body": {"balance": 100}})
        )
    )
    exchange = SimpleNamespace(publish=AsyncMock())
    main.app.state.redis = redis
    main.app.state.channel = SimpleNamespace(default_exchange=exchange)
    # No context manager: unit tests intentionally do not connect to infrastructure.
    return TestClient(main.app), exchange


def test_api_routes_only_allow_known_method_path(client):
    c, exchange = client
    assert c.get("/api/transfer/transfer").status_code == 404
    assert c.post("/api/auth/not-an-action", json={}).status_code == 404
    exchange.publish.assert_not_called()


@pytest.mark.parametrize("content", ["{broken", "[]", "null"])
def test_invalid_body_never_enters_queue(client, content):
    c, exchange = client
    assert c.post("/api/auth/login", content=content).status_code == 400
    exchange.publish.assert_not_called()


def test_published_transfer_preserves_retry_key_and_trace(client):
    c, exchange = client
    response = c.post(
        "/api/transfer/transfer",
        json={"to_username": "bob", "amount": 10},
        headers={"X-Session": "session", "Idempotency-Key": "same-key"},
    )
    assert response.status_code == 200
    message = exchange.publish.call_args.args[0]
    payload = json.loads(message.body)
    assert payload["key"] == "same-key"
    assert payload["session"] == "session"
    assert "traceparent" in payload["trace"]
    assert exchange.publish.call_args.kwargs["routing_key"] == "transfer.requests"


def test_dependency_failure_returns_retryable_error(client):
    c, exchange = client
    exchange.publish.side_effect = ConnectionError("private infrastructure address")
    response = c.get("/api/account/me")
    assert response.status_code == 503
    assert "private infrastructure address" not in response.text


def test_timeout_reports_unknown_outcome(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(main, "TIMEOUT", 0)
    response = c.post(
        "/api/transfer/transfer", json={"to_username": "bob", "amount": 10}
    )
    assert response.status_code == 504
    assert "SAME Idempotency-Key" in response.json()["detail"]
