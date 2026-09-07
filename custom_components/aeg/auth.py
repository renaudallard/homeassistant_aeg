# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""OneAccount authentication against the Electrolux OCP cloud.

This is the second half of the login. Gigya proves who the user is and hands
out a JWT; OneAccount trades that JWT for the access and refresh tokens the
appliance API expects, and renews them afterwards.
"""

from __future__ import annotations

import binascii
import json
import logging
import time
from base64 import b64encode, urlsafe_b64decode
from dataclasses import dataclass
from typing import Any

import aiohttp

from . import http
from .const import (
    API_KEY,
    BRAND,
    CLIENT_ID,
    CLIENT_SECRET,
    GRANT_CLIENT_CREDENTIALS,
    GRANT_REFRESH_TOKEN,
    GRANT_TOKEN_EXCHANGE,
    IDENTITY_PROVIDERS_PATH,
    OCP_BASE_URL,
    TOKEN_EXPIRY_MARGIN,
    TOKEN_PATH,
    TOKEN_PATH_V1,
)
from .errors import AegAuthError, AegConnectionError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentityProvider:
    """Where this user's account and appliances actually live.

    The app treats an empty base URL, or one equal to the global entry point,
    as a sign the account is not usable, so we do the same.
    """

    domain: str
    api_key: str
    brand: str
    http_base_url: str
    ws_base_url: str


@dataclass(frozen=True)
class Tokens:
    """An OCP access token with the refresh token that renews it."""

    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - TOKEN_EXPIRY_MARGIN


def _jwt_country(id_token: str) -> str | None:
    """Read the country the JWT was minted for.

    The Gigya JWT is asked for with the country field precisely so this header
    can carry it, which is more reliable than what the user picked.
    """
    try:
        claims_part = id_token.split(".")[1]
        padded = claims_part + "=" * (-len(claims_part) % 4)
        claims = json.loads(urlsafe_b64decode(padded))
    except (IndexError, ValueError, binascii.Error):
        _LOGGER.debug("could not read the country out of the id token")
        return None
    country = claims.get("country")
    return str(country) if country else None


def _tokens_from(payload: dict[str, Any]) -> Tokens:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise AegAuthError("OneAccount did not return a token pair")
    # A missing lifetime is treated as already expired, so the next call
    # refreshes rather than sending a token we cannot reason about.
    expires_in = float(payload.get("expires_in", 0))
    return Tokens(
        access_token=str(access_token),
        refresh_token=str(refresh_token),
        expires_at=time.time() + expires_in,
    )


class AegAuth:
    """Talks to the OneAccount half of the OCP API."""

    def __init__(self, session: aiohttp.ClientSession, country_code: str) -> None:
        self._session = session
        self._country = country_code.upper()

    def _headers(self, authorization: str | None = None) -> dict[str, str]:
        headers = {
            "x-api-key": API_KEY,
            "Origin-Country-Code": self._country,
        }
        if authorization is not None:
            headers["Authorization"] = authorization
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        status, payload = await http.request(
            self._session,
            method,
            url,
            headers=headers,
            params=params,
            json_body=json_body,
        )
        if status in (401, 403):
            raise AegAuthError(f"OneAccount rejected the credentials ({status})")
        if status >= 400:
            raise AegConnectionError(f"OneAccount refused the request ({status})")
        if payload is None:
            raise AegConnectionError(f"{url} returned an empty body")
        return payload

    async def client_credentials(self) -> str:
        """Authorise the application itself.

        The provider lookup is not anonymous. It wants a token that stands for
        the app rather than for a user, which is the one thing that has to
        happen before anybody signs in.
        """
        payload = await self._request(
            "POST",
            OCP_BASE_URL + TOKEN_PATH_V1,
            headers={"x-api-key": API_KEY},
            json_body={
                "grantType": GRANT_CLIENT_CREDENTIALS,
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET,
                "scope": "",
            },
        )
        token = payload.get("accessToken")
        if not token:
            raise AegAuthError("OneAccount did not return an application token")
        return f"{payload.get('tokenType', 'Bearer')} {token}"

    async def identity_provider(self) -> IdentityProvider:
        """Look up the Gigya tenant and regional endpoints for this country."""
        payload = await self._request(
            "GET",
            OCP_BASE_URL + IDENTITY_PROVIDERS_PATH,
            headers=self._headers(await self.client_credentials()),
            params={"brand": BRAND, "countryCode": self._country},
        )
        if not isinstance(payload, list) or not payload:
            raise AegAuthError(
                f"OneAccount lists no identity provider for {self._country}"
            )
        # Prefer the entry for our brand, but take what is there if the field
        # does not say what we expect. The app logs a complaint about a missing
        # or global endpoint and carries on, so we do the same rather than
        # refusing an account the app itself would have signed in.
        entry = next(
            (item for item in payload if item.get("brand") == BRAND), payload[0]
        )
        _LOGGER.debug("identity provider fields: %s", sorted(entry))
        domain = entry.get("domain")
        api_key = entry.get("apiKey")
        if not domain or not api_key:
            raise AegAuthError(
                "OneAccount returned an identity provider with no Gigya tenant"
            )
        base_url = entry.get("httpRegionalBaseUrl") or OCP_BASE_URL
        if base_url == OCP_BASE_URL:
            _LOGGER.warning(
                "no regional endpoint for this account, using %s", OCP_BASE_URL
            )
        return IdentityProvider(
            domain=str(domain),
            api_key=str(api_key),
            brand=str(entry.get("brand") or BRAND),
            http_base_url=str(base_url),
            ws_base_url=str(entry.get("webSocketRegionalBaseUrl") or ""),
        )

    async def exchange(self, id_token: str) -> Tokens:
        """Trade a Gigya JWT for OCP tokens.

        This call carries no client secret. Only the refresh does.
        """
        headers = {
            "x-api-key": API_KEY,
            "Origin-Country-Code": _jwt_country(id_token) or self._country,
        }
        payload = await self._request(
            "POST",
            OCP_BASE_URL + TOKEN_PATH,
            headers=headers,
            json_body={
                "grant_type": GRANT_TOKEN_EXCHANGE,
                "client_id": CLIENT_ID,
                "id_token": id_token,
                "scope": "",
            },
        )
        return _tokens_from(payload)

    async def refresh(self, tokens: Tokens) -> Tokens:
        """Renew an access token.

        The refresh token rotates on every call, so the caller has to persist
        what comes back or the next start will fail.
        """
        credentials = b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        payload = await self._request(
            "POST",
            OCP_BASE_URL + TOKEN_PATH,
            headers=self._headers(f"Basic {credentials}"),
            json_body={
                "grant_type": GRANT_REFRESH_TOKEN,
                "refresh_token": tokens.refresh_token,
                "scope": "",
            },
        )
        return _tokens_from(payload)
