"""Gigya identity client.

The Electrolux OCP cloud does not authenticate users itself. It delegates to a
Gigya (SAP Customer Data Cloud) tenant and accepts the JWT that Gigya mints for
a logged in user. This module covers that half of the login: sign in to Gigya
and come back with the JWT that auth.py trades for OCP tokens.

The tenant is not fixed. Its API key and domain come from the OneAccount
identity-providers lookup, so no region is hardcoded here.
"""

from __future__ import annotations

import hmac
import logging
import time
from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import sha1
from random import SystemRandom
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

from . import http
from .errors import AegAuthError, AegConnectionError

_LOGGER = logging.getLogger(__name__)

# The OneApp ships version 7.1.2 of the Gigya Android SDK and tags its requests
# with it. Gigya uses the tag for its own telemetry.
_SDK_VERSION = "Android_7.1.2"

_random = SystemRandom()


@dataclass(frozen=True)
class GigyaIds:
    """Client identifiers Gigya hands out before anyone logs in."""

    gmid: str
    ucid: str


@dataclass(frozen=True)
class GigyaSession:
    """A logged in Gigya session, which carries the key to sign requests."""

    token: str
    secret: str


def _nonce() -> str:
    """Return a per request unique value, shaped like the one the SDK sends."""
    return f"{int(time.time() * 1000)}_{_random.randint(0, 2**31 - 1)}"


def _percent_encode(value: str) -> str:
    """Encode per OAuth 1.0a, which leaves only the unreserved set alone."""
    return quote(value, safe="")


def _normalized_url(url: str) -> str:
    """Lowercase scheme and host, drop a default port, cut query and fragment."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    default_port = 443 if scheme == "https" else 80
    authority = host if parts.port in (None, default_port) else f"{host}:{parts.port}"
    return f"{scheme}://{authority}{parts.path}"


def _signature_base(method: str, url: str, params: dict[str, str]) -> str:
    query = "&".join(
        f"{_percent_encode(key)}={_percent_encode(params[key])}"
        for key in sorted(params)
    )
    return "&".join(
        (method.upper(), _percent_encode(_normalized_url(url)), _percent_encode(query))
    )


def sign_request(secret: str, method: str, url: str, params: dict[str, str]) -> str:
    """Return the Gigya sig for a request signed with a session secret.

    The secret arrives base64 encoded and is the raw HMAC key once decoded. The
    Android SDK encodes the digest URL safe, while the established Python
    clients use plain base64 and work, so plain base64 is what we send.
    """
    digest = hmac.new(
        b64decode(secret), _signature_base(method, url, params).encode(), sha1
    ).digest()
    return b64encode(digest).decode()


def _session_from(payload: dict[str, Any]) -> GigyaSession:
    """Read a signable session out of a login response.

    Gigya only returns a token and secret pair for a mobile target. A browser
    target yields a cookie value instead, which cannot sign accounts.getJWT, so
    a missing pair here means the request went out with the wrong targetEnv.
    """
    info = payload.get("sessionInfo") or {}
    token = info.get("sessionToken")
    secret = info.get("sessionSecret")
    if not token or not secret:
        raise AegAuthError("Gigya login did not return a signable session")
    return GigyaSession(token=token, secret=secret)


class GigyaClient:
    """The handful of Gigya calls the OneApp makes to reach a JWT."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, domain: str
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._domain = domain

    def _url(self, api: str) -> str:
        """Gigya routes on the first segment of the method name."""
        namespace = api.split(".", 1)[0]
        return f"https://{namespace}.{self._domain}/{api}"

    async def _post(
        self,
        api: str,
        params: dict[str, str],
        session: GigyaSession | None = None,
    ) -> dict[str, Any]:
        url = self._url(api)
        body = {
            "apiKey": self._api_key,
            "format": "json",
            # Report Gigya side failures as HTTP status codes rather than
            # burying them in a 200 response.
            "httpStatusCodes": "true",
            "nonce": _nonce(),
            "sdk": _SDK_VERSION,
            # Mobile is what makes Gigya return a session token and secret
            # rather than a browser cookie value.
            "targetEnv": "mobile",
            **params,
        }
        if session is not None:
            body["oauth_token"] = session.token
            body["timestamp"] = str(int(time.time()))
            body["sig"] = sign_request(session.secret, "POST", url, body)
        return await self._request(url, body)

    async def _request(self, url: str, body: dict[str, str]) -> dict[str, Any]:
        """Post a form body and map the outcome onto our error types.

        These endpoints only fail over credentials or availability, so a 4xx
        other than 429 is reported as an authentication problem.
        """
        status, payload = await http.request(self._session, "POST", url, data=body)
        if status == 429:
            raise AegConnectionError("Gigya is rate limiting this client")
        if status >= 400:
            details = payload if isinstance(payload, dict) else {}
            message = details.get("errorMessage", "no message")
            code = details.get("errorCode", "none")
            raise AegAuthError(f"Gigya rejected the request: {message} (code {code})")
        if not isinstance(payload, dict):
            raise AegConnectionError("Gigya returned no object to read")
        return payload

    async def ids(self) -> GigyaIds:
        """Fetch the identifiers that every later call is expected to carry."""
        payload = await self._post("socialize.getIDs", {})
        gmid = payload.get("gmid")
        ucid = payload.get("ucid")
        if not gmid or not ucid:
            raise AegConnectionError("Gigya did not return gmid and ucid")
        return GigyaIds(gmid=gmid, ucid=ucid)

    async def login(self, email: str, password: str, ids: GigyaIds) -> GigyaSession:
        """Sign in with an email and password."""
        payload = await self._post(
            "accounts.login",
            {
                "loginID": email,
                "password": password,
                "gmid": ids.gmid,
                "ucid": ids.ucid,
            },
        )
        return _session_from(payload)

    async def send_otp_code(self, email: str, ids: GigyaIds) -> str:
        """Mail a one time code to the account and return the token to quote back."""
        payload = await self._post(
            "accounts.auth.otp.email.sendCode",
            {"email": email, "gmid": ids.gmid, "ucid": ids.ucid},
        )
        vtoken = payload.get("vToken")
        if not vtoken:
            raise AegAuthError("Gigya did not return a vToken for the code request")
        return str(vtoken)

    async def login_with_otp(
        self, code: str, vtoken: str, ids: GigyaIds
    ) -> GigyaSession:
        """Sign in with a one time code, which keeps the password out of here."""
        payload = await self._post(
            "accounts.auth.otp.email.login",
            {"code": code, "vToken": vtoken, "gmid": ids.gmid, "ucid": ids.ucid},
        )
        return _session_from(payload)

    async def jwt(self, session: GigyaSession, ids: GigyaIds) -> str:
        """Mint the JWT that the OCP token exchange accepts.

        The country field is what the OneApp asks for, and OneAccount uses it
        to place the user in a region.
        """
        payload = await self._post(
            "accounts.getJWT",
            {"fields": "country", "gmid": ids.gmid, "ucid": ids.ucid},
            session=session,
        )
        token = payload.get("id_token")
        if not token:
            raise AegAuthError("Gigya did not return an id_token")
        return str(token)
