"""HTTP client for the Java (SpringBoot) backend.

Wraps ``httpx.AsyncClient`` with:
- base URL + API prefix construction
- Bearer token auth (access + refresh)
- unified error handling
- connection-pool lifecycle tied to FastAPI lifespan
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_client: JavaClient | None = None


class JavaClientError(Exception):
    """Raised when the Java backend returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str, url: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__(f"Java API {status_code}: {detail} ({url})")


class JavaClient:
    """Async HTTP client for the SpringBoot backend."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = f"{settings.spring_boot_base_url.rstrip('/')}{settings.spring_boot_api_prefix}"
        self._timeout = settings.spring_boot_timeout
        self._access_token = settings.spring_boot_access_token
        self._refresh_token = settings.spring_boot_refresh_token
        self._http: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying ``httpx.AsyncClient`` connection pool."""
        if self._http is not None:
            return
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
            headers=self._auth_headers(),
            verify=False,  # internal API – skip TLS verification
        )
        logger.info("JavaClient started — base_url=%s", self._base_url)

    async def close(self) -> None:
        """Gracefully close the connection pool."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None
            logger.info("JavaClient closed")

    # -- public API ----------------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Send a GET request and return the parsed JSON body.

        Raises :class:`JavaClientError` on non-2xx responses.
        """
        client = self._ensure_started()
        url = path
        logger.debug("GET %s params=%s", url, params)
        response = await client.get(url, params=params)
        return self._handle_response(response)

    async def post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        """Send a POST request and return the parsed JSON body."""
        client = self._ensure_started()
        url = path
        logger.debug("POST %s", url)
        response = await client.post(url, json=json_body)
        return self._handle_response(response)

    # -- token management ----------------------------------------------------

    def update_tokens(self, access_token: str, refresh_token: str | None = None) -> None:
        """Hot-swap tokens without recreating the client."""
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token
        if self._http is not None:
            self._http.headers.update(self._auth_headers())
        logger.info("JavaClient tokens updated")

    # -- internals -----------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _ensure_started(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("JavaClient not started — call await client.start() first")
        return self._http

    def _handle_response(self, response: httpx.Response) -> Any:
        """Parse a JSON response; raise on errors."""
        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise JavaClientError(
                status_code=response.status_code,
                detail=detail,
                url=str(response.url),
            )
        if not response.text:
            return {}
        return response.json()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

def get_java_client() -> JavaClient:
    """Return the module-level JavaClient singleton (create if needed)."""
    global _client
    if _client is None:
        _client = JavaClient()
    return _client
