"""Tests for services/java_client.py — HTTP client for Java backend."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.java_client import JavaClient, JavaClientError, get_java_client


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
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"code":200,"data":[1,2,3]}'
    mock_response.json.return_value = {"code": 200, "data": [1, 2, 3]}

    await client.start()
    client._http.get = AsyncMock(return_value=mock_response)

    result = await client.get("/dify/teacher/t-001/classes/me")
    assert result == {"code": 200, "data": [1, 2, 3]}
    await client.close()


@pytest.mark.asyncio
async def test_get_404_raises(client):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.url = "https://api.example.com/api/dify/teacher/bad/classes/me"

    await client.start()
    client._http.get = AsyncMock(return_value=mock_response)

    with pytest.raises(JavaClientError) as exc_info:
        await client.get("/dify/teacher/bad/classes/me")
    assert exc_info.value.status_code == 404
    await client.close()


@pytest.mark.asyncio
async def test_post_success(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"code":200,"data":{"ok":true}}'
    mock_response.json.return_value = {"code": 200, "data": {"ok": True}}

    await client.start()
    client._http.post = AsyncMock(return_value=mock_response)

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
# Singleton
# ---------------------------------------------------------------------------

def test_get_java_client_singleton():
    import services.java_client as mod
    mod._client = None  # reset
    c1 = get_java_client()
    c2 = get_java_client()
    assert c1 is c2
    mod._client = None  # cleanup
