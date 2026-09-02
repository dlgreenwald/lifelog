"""Resource Owner Password Credentials authenticator for the device simulator.

Interaction-free: POST username/password + client credentials to the token endpoint.
No browser, no redirect URI.
"""

from __future__ import annotations

import os
import time

import httpx


class DeviceAuthenticator:
    """Obtains and caches OIDC tokens via password grant.

    Interaction-free — suitable for automated tests.
    Env vars:
        DEVICE_SIM_OIDC_ISSUER:  OIDC provider discovery URL.
        DEVICE_SIM_CLIENT_ID:    OAuth client ID (confidential client with password grant).
        DEVICE_SIM_CLIENT_SECRET: OAuth client secret.
        DEVICE_SIM_USERNAME:     Username for the test user account.
        DEVICE_SIM_PASSWORD:     Password for the test user account.
        DEVICE_SIM_SERVER_URL:  Base URL of the lifelog server.
    """

    def __init__(self) -> None:
        self._issuer = os.environ["DEVICE_SIM_OIDC_ISSUER"]
        self._client_id = os.environ["DEVICE_SIM_CLIENT_ID"]
        self._client_secret = os.environ.get("DEVICE_SIM_CLIENT_SECRET", "")
        self._username = os.environ["DEVICE_SIM_USERNAME"]
        self._password = os.environ["DEVICE_SIM_PASSWORD"]
        self._server_url = os.environ["DEVICE_SIM_SERVER_URL"]
        self._discovery: dict | None = None
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def _discover(self) -> dict:
        if self._discovery is None:
            well_known = f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
            resp = httpx.get(well_known, timeout=10)
            resp.raise_for_status()
            self._discovery = resp.json()
        return self._discovery

    @property
    def token_endpoint(self) -> str:
        return self._discover()["token_endpoint"]  # type: ignore[return-value]

    def refresh(self) -> str:
        payload = {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
            "client_id": self._client_id,
            "scope": "openid",
        }
        if self._client_secret:
            payload["client_secret"] = self._client_secret

        resp = httpx.post(self.token_endpoint, data=payload, timeout=10)
        resp.raise_for_status()
        token_resp = resp.json()
        expires_in: int = token_resp.get("expires_in", 3600)
        self._access_token = token_resp["access_token"]
        self._expires_at = time.time() + expires_in - 60
        return self._access_token

    def get_token(self) -> str:
        if self._access_token is None or time.time() >= self._expires_at:
            return self.refresh()
        return self._access_token

    def get_bearer(self) -> str:
        return self.get_token()

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}"}


def get_bearer_token(auth: DeviceAuthenticator) -> str:
    return auth.get_token()
