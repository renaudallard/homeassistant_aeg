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
from base64 import urlsafe_b64decode
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
    TOKEN_PATH_V1,
)
from .errors import AegAuthError, AegConnectionError, AegTooManyRequests

_LOGGER = logging.getLogger(__name__)

# What an error body calls the reason OneAccount itself gave, and the reason
# that means the credentials are spent rather than the request being wrong.
ONE_ACCOUNT_ERROR = "oneAccountError"
INVALID_GRANT = "invalid_grant"


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
        """Due for renewal, counting the margin."""
        return time.time() >= self.expires_at - TOKEN_EXPIRY_MARGIN

    @property
    def usable(self) -> bool:
        """Still accepted by the service, margin or no margin."""
        return time.time() < self.expires_at


def _detail(payload: Any) -> str:
    """A short printable form of an error body, to say why a call was refused."""
    if payload is None:
        return "no body"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return text[:300]


def _turned_down(status: int, payload: Any) -> bool:
    """Whether a refusal is about the account rather than about the request.

    A refresh token OneAccount will not take again is turned down with a 400
    saying so in the body, rather than with the 401 the same rejection gets
    everywhere else. The app reads that field alongside the status and treats
    the two alike, so an entry holding a pair that has gone stale asks for a
    new sign in rather than retrying a call that cannot come good.

    Only a refusal is read this way. An answer that worked is an answer that
    worked, whatever else it happens to carry.
    """
    if status < 400 or not isinstance(payload, dict):
        return False
    return bool(payload.get(ONE_ACCOUNT_ERROR) == INVALID_GRANT)


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


def _lifetime(payload: dict[str, Any]) -> float:
    """How long a token is good for, in seconds.

    A lifetime that is missing, or that arrives as something no number can be
    read out of, is treated as none at all: the pair is then due for renewal
    the moment it is used rather than being sent anywhere on a guess. Reading
    it is the one step here that can fail over the shape of an answer rather
    than over the credentials, and everything above expects the errors of this
    module rather than those of the standard library.
    """
    given = payload.get("expiresIn")
    if given is None:
        given = payload.get("expires_in")
    if given is None:
        return 0.0
    try:
        return float(given)
    except (TypeError, ValueError):
        _LOGGER.debug("could not read how long the token lasts from %r", given)
        return 0.0


def _tokens_from(payload: dict[str, Any]) -> Tokens:
    # v1 names its fields the way the rest of the API does, in camelCase. The
    # v2 endpoint the app uses answers in snake_case, which is the only reason
    # both spellings are read here.
    access_token = payload.get("accessToken") or payload.get("access_token")
    refresh_token = payload.get("refreshToken") or payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise AegAuthError("OneAccount did not return a token pair")
    return Tokens(
        access_token=str(access_token),
        refresh_token=str(refresh_token),
        expires_at=time.time() + _lifetime(payload),
    )


class AegAuth:
    """Talks to the OneAccount half of the OCP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        country_code: str,
        base_url: str = OCP_BASE_URL,
    ) -> None:
        self._session = session
        self._country = country_code.upper()
        # Token calls go to the regional endpoint once it is known. The app
        # caches it the same way and falls back to the global one until the
        # provider lookup has run, which is the only call that cannot use it.
        self._base_url = base_url.rstrip("/")

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
        if status == 429:
            raise AegTooManyRequests(f"OneAccount is throttling: {_detail(payload)}")
        if status in (401, 403) or _turned_down(status, payload):
            raise AegAuthError(
                f"OneAccount rejected the credentials ({status}): {_detail(payload)}"
            )
        if status >= 400:
            raise AegConnectionError(
                f"OneAccount refused the request ({status}): {_detail(payload)}"
            )
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
        # Everything after this point talks to the regional endpoint.
        self._base_url = str(base_url).rstrip("/")
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
            self._base_url + TOKEN_PATH_V1,
            headers=headers,
            json_body={
                "grantType": GRANT_TOKEN_EXCHANGE,
                "clientId": CLIENT_ID,
                "clientSecret": None,
                "idToken": id_token,
                "refreshToken": None,
                "scope": "",
            },
        )
        return _tokens_from(payload)

    async def refresh(self, tokens: Tokens) -> Tokens:
        """Renew an access token.

        The refresh token rotates on every call, so the caller has to persist
        what comes back or the next start will fail.
        """
        payload = await self._request(
            "POST",
            self._base_url + TOKEN_PATH_V1,
            headers=self._headers(),
            json_body={
                "grantType": GRANT_REFRESH_TOKEN,
                "clientId": CLIENT_ID,
                "clientSecret": None,
                "idToken": None,
                "refreshToken": tokens.refresh_token,
                "scope": "",
            },
        )
        return _tokens_from(payload)
