#!/usr/bin/env python
"""Script to refresh the access token using the refresh token."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from config.settings import get_settings


async def refresh_token():
    """Try to refresh the access token."""
    settings = get_settings()

    base_url = settings.spring_boot_base_url.rstrip("/")
    refresh_token = settings.spring_boot_refresh_token

    print("=" * 60)
    print("TOKEN REFRESH ATTEMPT")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"Refresh Token: {refresh_token[:50]}..." if refresh_token else "Refresh Token: (not set)")

    # Common refresh endpoints to try
    endpoints = [
        "/api/auth/refresh",
        "/api/auth/token/refresh",
        "/api/user/refresh",
        "/auth/refresh",
        "/api/dify/auth/refresh",
    ]

    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            print(f"\n--- Trying: POST {url}")

            # Try different payload formats
            payloads = [
                {"refreshToken": refresh_token},
                {"refresh_token": refresh_token},
                {"token": refresh_token},
            ]

            headers_options = [
                {"Authorization": f"Bearer {refresh_token}"},
                {"Content-Type": "application/json"},
                {"Authorization": f"Bearer {refresh_token}", "Content-Type": "application/json"},
            ]

            for headers in headers_options:
                for payload in payloads:
                    try:
                        response = await client.post(url, json=payload, headers=headers)
                        print(f"  Status: {response.status_code}")
                        if response.status_code == 200:
                            data = response.json()
                            print(f"  [SUCCESS] Response: {json.dumps(data, indent=2)}")

                            # Extract new tokens
                            new_access = data.get("accessToken") or data.get("access_token") or data.get("data", {}).get("accessToken")
                            new_refresh = data.get("refreshToken") or data.get("refresh_token") or data.get("data", {}).get("refreshToken")

                            if new_access:
                                print(f"\n  NEW ACCESS TOKEN: {new_access[:50]}...")
                            if new_refresh:
                                print(f"  NEW REFRESH TOKEN: {new_refresh[:50]}...")
                            return data
                        elif response.status_code != 404:
                            print(f"  Response: {response.text[:200]}")
                    except httpx.ConnectError as e:
                        print(f"  Connection error: {e}")
                    except Exception as e:
                        print(f"  Error: {e}")

    print("\n[FAILED] Could not refresh token with any endpoint/payload combination")
    return None


if __name__ == "__main__":
    asyncio.run(refresh_token())
