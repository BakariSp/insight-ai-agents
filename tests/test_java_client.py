"""Tests for services/java_client.py — HTTP client for Java backend."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from services.java_client import (
    JavaClient,
    JavaClientError,
    CircuitOpenError,
    get_java_client,
    CIRCUIT_OPEN_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a fresh JavaClient for each test (not the global singleton)."""
    with patch("services.java_client.get_settings") as mock_settings:
        s = MagicMock()
        s.spring_boot_base_url = "https://api.example.com"
        s.spring_boot_api_prefix = "/api"
        s.spring_boot_timeout = 10
        s.spring_boot_access_token = "test-token"
        s.spring_boot_refresh_token = "test-refresh"
        mock_settings.return_value = s
        yield JavaClient()


def _ok_response(data=None):
    r = MagicMock()
    r.status_code = 200
    r.text = '{"ok":true}'
    r.json.return_value = data or {"ok": True}
    return r


def _error_response(status=500):
    r = MagicMock()
    r.status_code = status
    r.text = "Server Error"
    r.url = "https://api.example.com/api/test"
    return r


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_base_url_constructed(client):
    assert client._base_url == "https://api.example.com/api"


def test_auth_headers(client):
    headers = client._auth_headers()
    assert headers["Authorization"] == "Bearer test-token"


def test_auth_headers_empty_token():
    with patch("services.java_client.get_settings") as mock_settings:
        s = MagicMock()
        s.spring_boot_base_url = "https://api.example.com"
        s.spring_boot_api_prefix = "/api"
        s.spring_boot_timeout = 10
        s.spring_boot_access_token = ""
        s.spring_boot_refresh_token = ""
        mock_settings.return_value = s
        c = JavaClient()
    assert c._auth_headers() == {}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_creates_http_client(client):
    await client.start()
    assert client._http is not None
    await client.close()


@pytest.mark.asyncio
async def test_close_sets_http_none(client):
    await client.start()
    await client.close()
    assert client._http is None


@pytest.mark.asyncio
async def test_ensure_started_raises_without_start(client):
    with pytest.raises(RuntimeError, match="not started"):
        client._ensure_started()


# ---------------------------------------------------------------------------
# GET / POST with mocked httpx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_success(client):
    await client.start()
    client._http.get = AsyncMock(return_value=_ok_response({"code": 200, "data": [1, 2, 3]}))

    result = await client.get("/dify/teacher/t-001/classes/me")
    assert result == {"code": 200, "data": [1, 2, 3]}
    await client.close()


@pytest.mark.asyncio
async def test_get_404_raises(client):
    r = MagicMock()
    r.status_code = 404
    r.text = "Not Found"
    r.url = "https://api.example.com/api/dify/teacher/bad/classes/me"

    await client.start()
    client._http.get = AsyncMock(return_value=r)

    with pytest.raises(JavaClientError) as exc_info:
        await client.get("/dify/teacher/bad/classes/me")
    assert exc_info.value.status_code == 404
    await client.close()


@pytest.mark.asyncio
async def test_post_success(client):
    await client.start()
    client._http.post = AsyncMock(return_value=_ok_response({"data": {"ok": True}}))

    result = await client.post("/some/path", json_body={"key": "val"})
    assert result["data"]["ok"] is True
    await client.close()


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_tokens(client):
    await client.start()
    client.update_tokens("new-access", "new-refresh")
    assert client._access_token == "new-access"
    assert client._refresh_token == "new-refresh"
    assert client._http.headers["Authorization"] == "Bearer new-access"
    await client.close()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_5xx_then_success(client):
    """Should retry on 500 and succeed on 2nd attempt."""
    await client.start()
    client._http.get = AsyncMock(
        side_effect=[_error_response(500), _ok_response({"recovered": True})]
    )

    with patch("services.java_client.RETRY_BASE_DELAY", 0):
        result = await client.get("/test")

    assert result == {"recovered": True}
    assert client._http.get.call_count == 2
    assert client._consecutive_failures == 0  # success resets counter
    await client.close()


@pytest.mark.asyncio
async def test_retry_exhausted_raises(client):
    """Should raise after MAX_RETRIES 5xx responses."""
    await client.start()
    client._http.get = AsyncMock(return_value=_error_response(503))

    with patch("services.java_client.RETRY_BASE_DELAY", 0), \
         patch("services.java_client.MAX_RETRIES", 2):
        with pytest.raises(JavaClientError) as exc_info:
            await client.get("/test")

    assert exc_info.value.status_code == 503
    assert client._http.get.call_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_retry_on_network_error(client):
    """Should retry on transport errors."""
    await client.start()
    client._http.get = AsyncMock(
        side_effect=[httpx.ConnectError("refused"), _ok_response({"ok": True})]
    )

    with patch("services.java_client.RETRY_BASE_DELAY", 0):
        result = await client.get("/test")

    assert result == {"ok": True}
    await client.close()


@pytest.mark.asyncio
async def test_no_retry_on_4xx(client):
    """4xx errors should NOT be retried — raised immediately."""
    r = MagicMock()
    r.status_code = 400
    r.text = "Bad Request"
    r.url = "https://api.example.com/api/test"

    await client.start()
    client._http.get = AsyncMock(return_value=r)

    with pytest.raises(JavaClientError) as exc_info:
        await client.get("/test")

    assert exc_info.value.status_code == 400
    assert client._http.get.call_count == 1  # no retry
    await client.close()


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def test_circuit_initially_closed(client):
    assert client.circuit_open is False


def test_circuit_opens_after_threshold(client):
    for _ in range(CIRCUIT_OPEN_THRESHOLD):
        client._record_failure()
    assert client.circuit_open is True


def test_circuit_resets_on_success(client):
    for _ in range(CIRCUIT_OPEN_THRESHOLD):
        client._record_failure()
    assert client.circuit_open is True

    client._record_success()
    assert client.circuit_open is False
    assert client._consecutive_failures == 0


@pytest.mark.asyncio
async def test_circuit_open_raises_immediately(client):
    """When circuit is open, requests should fail fast without hitting the server."""
    for _ in range(CIRCUIT_OPEN_THRESHOLD):
        client._record_failure()

    with pytest.raises(CircuitOpenError):
        await client.get("/test")


def test_circuit_half_open_after_timeout(client):
    """After CIRCUIT_RESET_TIMEOUT, circuit should become half-open."""
    for _ in range(CIRCUIT_OPEN_THRESHOLD):
        client._record_failure()

    assert client.circuit_open is True

    # Simulate timeout elapsed
    import time
    client._circuit_opened_at = time.monotonic() - 120  # well past timeout
    assert client.circuit_open is False  # half-open


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_get_java_client_singleton():
    import services.java_client as mod
    mod._client = None  # reset
    c1 = get_java_client()
    c2 = get_java_client()
    assert c1 is c2
    mod._client = None  # cleanup
