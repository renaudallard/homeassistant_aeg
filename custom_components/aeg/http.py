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

"""Shared HTTP plumbing.

Every cloud call goes through here, so an unreachable host or an unreadable
body is reported the same way wherever it happens. What a given status means is
left to the caller, because it differs between the identity endpoints and the
appliance endpoints.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import CONNECT_TIMEOUT, REQUEST_TIMEOUT
from .errors import AegBackendError, AegConnectionError

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)

# Anything under one of these names is a credential, a token or the identity of
# the person using it. Debug logging is meant to be pasted into a bug report,
# so none of it goes out in the clear.
SECRETS = frozenset(
    {
        "access_token",
        "accesstoken",
        "apikey",
        "authorization",
        "client_secret",
        "clientsecret",
        "code",
        "cookievalue",
        "email",
        "gmid",
        "id_token",
        "idtoken",
        "loginid",
        "oauth_token",
        "password",
        "refresh_token",
        "refreshtoken",
        "sessionsecret",
        "sessiontoken",
        "sig",
        "ucid",
        "vtoken",
        "x-api-key",
    }
)


def redact(data: Any) -> Any:
    """Copy a structure with every secret replaced by a note of its length."""
    if isinstance(data, dict):
        return {
            key: (
                f"<{len(value)} chars hidden>"
                if str(key).lower() in SECRETS and isinstance(value, str) and value
                else redact(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(item) for item in data]
    return data


def _readable(body: bytes) -> str:
    """A body fit to log: redacted if it is JSON, described if it is not."""
    if not body:
        return "empty"
    try:
        return json.dumps(redact(json.loads(body)))[:2000]
    except ValueError:
        return f"<{len(body)} bytes that are not JSON>"


async def request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    """Make a request and return the status along with the decoded body.

    Raises when there is no answer worth reading, meaning an unreachable host, a
    server side failure, or a body that does not parse. An empty body is fine
    and reads back as None.
    """
    _LOGGER.debug("%s %s params=%s", method, url, params)
    _LOGGER.debug("  headers %s", redact(dict(headers or {})))
    if data is not None:
        _LOGGER.debug("  form %s", redact(data))
    if json_body is not None:
        _LOGGER.debug("  json %s", redact(json_body))
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            json=json_body,
            timeout=TIMEOUT,
        ) as response:
            status = response.status
            body = await response.read()
            _LOGGER.debug("  <- %s %s", status, dict(response.headers))
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("  <- did not answer: %s", err)
        raise AegConnectionError(f"{url} is unreachable: {err}") from err

    _LOGGER.debug("  <- body %s", _readable(body))

    if status >= 500:
        raise AegBackendError(f"{url} failed with status {status}")
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError as err:
        raise AegConnectionError(
            f"{url} answered status {status} with a body that is not JSON"
        ) from err
