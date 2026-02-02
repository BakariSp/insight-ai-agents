"""HTTP client for the Java (SpringBoot) backend.

Wraps ``httpx.AsyncClient`` with:
- base URL + API prefix construction
- Bearer token auth (access + refresh)
- retry with exponential backoff (network / 5xx errors)
- circuit breaker: auto-degrade to mock after N consecutive failures
- request timing logs
- connection-pool lifecycle tied to FastAPI lifespan
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_client: JavaClient | None = None

# Retry / circuit breaker defaults
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5  # seconds, doubles each attempt
CIRCUIT_OPEN_THRESHOLD = 5  # consecutive failures before circuit opens
CIRCUIT_RESET_TIMEOUT = 60  # seconds before attempting to close circuit


class JavaClientError(Exception):
    """Raised when the Java backend returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str, url: str = ""):
        self.status_code = status_code
        self.detail = detail
        self.url = url
        super().__init__(f"Java API {status_code}: {detail} ({url})")


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open (backend deemed unavailable)."""

    def __init__(self):
        super().__init__(
            "Circuit breaker open — Java backend unavailable, "
            "falling back to mock data"
        )


class JavaClient:
    """Async HTTP client for the SpringBoot backend with retry and circuit breaker."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = f"{settings.spring_boot_base_url.rstrip('/')}{settings.spring_boot_api_prefix}"
        self._timeout = settings.spring_boot_timeout
        self._access_token = settings.spring_boot_access_token
        self._refresh_token = settings.spring_boot_refresh_token
        self._http: httpx.AsyncClient | None = None

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_opened_at: float | None = None

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
        """Send a GET request with retry and circuit-breaker logic.

        Raises :class:`JavaClientError` on non-retryable errors (4xx).
        Raises :class:`CircuitOpenError` when circuit is open.
        """
        return await self._request_with_retry("GET", path, params=params)

    async def post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        """Send a POST request with retry and circuit-breaker logic."""
        return await self._request_with_retry("POST", path, json_body=json_body)

    # -- token management ----------------------------------------------------

    def update_tokens(self, access_token: str, refresh_token: str | None = None) -> None:
        """Hot-swap tokens without recreating the client."""
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token
        if self._http is not None:
            self._http.headers.update(self._auth_headers())
        logger.info("JavaClient tokens updated")

    # -- circuit breaker -----------------------------------------------------

    @property
    def circuit_open(self) -> bool:
        """True when the backend is deemed unavailable."""
        if self._consecutive_failures < CIRCUIT_OPEN_THRESHOLD:
            return False
        # Check if reset timeout elapsed (half-open → try one request)
        if self._circuit_opened_at is not None:
            elapsed = time.monotonic() - self._circuit_opened_at
            if elapsed >= CIRCUIT_RESET_TIMEOUT:
                logger.info("Circuit breaker half-open — attempting probe request")
                return False
        return True

    def _record_success(self) -> None:
        if self._consecutive_failures > 0:
            logger.info(
                "Java backend recovered after %d consecutive failures",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._circuit_opened_at = None

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_OPEN_THRESHOLD and self._circuit_opened_at is None:
            self._circuit_opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker OPEN — %d consecutive failures, "
                "will retry after %ds",
                self._consecutive_failures,
                CIRCUIT_RESET_TIMEOUT,
            )

    # -- retry logic ---------------------------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request with exponential-backoff retry.

        Retries on:
        - Network errors (``httpx.TransportError``)
        - Server errors (5xx)

        Does NOT retry on:
        - Client errors (4xx) — raised immediately
        - Circuit breaker open — raised immediately
        """
        if self.circuit_open:
            raise CircuitOpenError()

        client = self._ensure_started()
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            t0 = time.monotonic()
            try:
                if method == "GET":
                    response = await client.get(path, params=params)
                else:
                    response = await client.post(path, json=json_body)

                elapsed_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "%s %s → %d (%.0fms)",
                    method, path, response.status_code, elapsed_ms,
                )

                # 4xx: non-retryable client error
                if 400 <= response.status_code < 500:
                    self._record_success()  # server is alive
                    detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
                    raise JavaClientError(
                        status_code=response.status_code,
                        detail=detail,
                        url=str(response.url),
                    )

                # 5xx: retryable server error
                if response.status_code >= 500:
                    self._record_failure()
                    last_exc = JavaClientError(
                        status_code=response.status_code,
                        detail=response.text[:200] if response.text else "",
                        url=str(response.url),
                    )
                    if attempt < MAX_RETRIES:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "%s %s → 5xx, retry %d/%d in %.1fs",
                            method, path, attempt, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise last_exc

                # Success
                self._record_success()
                if not response.text:
                    return {}
                return response.json()

            except httpx.TransportError as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                self._record_failure()
                last_exc = exc
                logger.warning(
                    "%s %s → network error (%.0fms): %s [attempt %d/%d]",
                    method, path, elapsed_ms, exc, attempt, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue

        # Exhausted all retries
        raise last_exc  # type: ignore[misc]

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


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

def get_java_client() -> JavaClient:
    """Return the module-level JavaClient singleton (create if needed)."""
    global _client
    if _client is None:
        _client = JavaClient()
    return _client
