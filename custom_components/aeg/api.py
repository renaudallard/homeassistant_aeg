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

"""The appliance half of the Electrolux OCP API.

Everything here needs an access token, so the client owns the token pair and
renews it when it goes stale. Renewal rotates the refresh token, and a caller
that does not store the new one locks itself out, so the client reports every
new pair through a listener.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from . import http
from .auth import AegAuth, Tokens
from .const import API_KEY, APPLIANCES_PATH, TOKEN_EXPIRY_MARGIN
from .errors import AegAuthError, AegConnectionError, AegTooManyRequests
from .http import redact_url

_LOGGER = logging.getLogger(__name__)

TokenListener = Callable[[Tokens], Awaitable[None]]


def _expect_object(payload: Any, what: str) -> dict[str, Any]:
    """Guard against a body that is not the object we asked for."""
    if not isinstance(payload, dict):
        raise AegConnectionError(f"the cloud returned no {what} object")
    return payload


class AegApi:
    """Reads appliance state and sends commands."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: AegAuth,
        tokens: Tokens,
        base_url: str,
        country_code: str,
        on_tokens: TokenListener | None = None,
    ) -> None:
        self._session = session
        self._auth = auth
        self._tokens = tokens
        self._base_url = base_url.rstrip("/")
        self._country = country_code.upper()
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> Tokens:
        """The current token pair, which changes on every renewal."""
        return self._tokens

    def seconds_until_renewal(self) -> float:
        """How long the token in hand is good for, less the margin.

        The stream holds one connection open for as long as it is allowed to,
        so it has to know when the token it opened with stops being worth
        anything.
        """
        return max(0.0, self._tokens.expires_at - TOKEN_EXPIRY_MARGIN - time.time())

    async def authorization(self) -> str:
        """A bearer header, renewed if it is due. The stream reconnects with it."""
        return f"Bearer {await self._access_token()}"

    async def _store(self, tokens: Tokens) -> None:
        self._tokens = tokens
        if self._on_tokens is not None:
            await self._on_tokens(tokens)

    async def _access_token(self) -> str:
        async with self._lock:
            if self._tokens.expired:
                try:
                    await self._store(await self._auth.refresh(self._tokens))
                except AegTooManyRequests:
                    # Renewing a token that was issued moments ago is refused.
                    # The one in hand is good until it actually expires, so use
                    # it rather than failing an update over the margin.
                    if not self._tokens.usable:
                        raise
                    _LOGGER.debug("renewal refused as too soon, keeping the token")
            return self._tokens.access_token

    async def _renew(self, rejected: str) -> None:
        """Renew a token the service turned down, unless someone beat us to it."""
        async with self._lock:
            if self._tokens.access_token != rejected:
                return
            await self._store(await self._auth.refresh(self._tokens))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        token = await self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": API_KEY,
            "Origin-Country-Code": self._country,
        }
        url = self._base_url + path
        status, payload = await http.request(
            self._session,
            method,
            url,
            headers=headers,
            params=params,
            json_body=json_body,
        )
        if status == 401 and retry:
            # The token was refused early. Renew once and try again, so a clock
            # that drifted or a token revoked server side does not surface as a
            # failed update.
            await self._renew(token)
            return await self._request(
                method, path, params=params, json_body=json_body, retry=False
            )
        if status in (401, 403):
            raise AegAuthError(
                f"{redact_url(url)} rejected the access token ({status})"
            )
        if status >= 400:
            raise AegConnectionError(
                f"{redact_url(url)} refused the request ({status})"
            )
        return payload

    async def appliances(self) -> list[dict[str, Any]]:
        """List the appliances on the account, with their metadata."""
        payload = await self._request(
            "GET", APPLIANCES_PATH, params={"includeMetadata": "true"}
        )
        if not isinstance(payload, list):
            raise AegConnectionError("the cloud returned no appliance list")
        return payload

    async def appliance(self, appliance_id: str) -> dict[str, Any]:
        """Read one appliance, which is where the live state lives."""
        payload = await self._request(
            "GET",
            f"{APPLIANCES_PATH}/{appliance_id}",
            params={"includeMetadata": "true"},
        )
        return _expect_object(payload, "appliance")

    async def capabilities(self, appliance_id: str) -> dict[str, Any]:
        """Read the capability tree that describes what this model can do."""
        payload = await self._request(
            "GET", f"{APPLIANCES_PATH}/{appliance_id}/capabilities"
        )
        return _expect_object(payload, "capability")

    async def send_command(self, appliance_id: str, command: dict[str, Any]) -> None:
        """Send a command, shaped as the capability tree says it should be."""
        await self._request(
            "PUT", f"{APPLIANCES_PATH}/{appliance_id}/command", json_body=command
        )
