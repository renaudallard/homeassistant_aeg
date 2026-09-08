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

# Anything under one of these names is a credential, a token, or says who the
# account belongs to and which appliance is theirs. Debug logging is meant to be
# pasted into a bug report, so none of it goes out in the clear.
#
# "state" is deliberately absent: it is a profile field, but it is also what an
# appliance calls the thing we most want to read in a log.
SECRETS = frozenset(
    {
        "access_token",
        "accesstoken",
        "address",
        "apikey",
        "applianceid",
        "authorization",
        "birthday",
        "birthyear",
        "city",
        "client_secret",
        "clientsecret",
        "code",
        "cookievalue",
        "email",
        "firstname",
        "gcid",
        "gmid",
        "id_token",
        "idtoken",
        "lastname",
        "loginid",
        "nickname",
        "oauth_token",
        "password",
        "phone",
        "phonenumber",
        "refresh_token",
        "refreshtoken",
        "sessionsecret",
        "sessiontoken",
        "sig",
        "ucid",
        "uid",
        "uidsignature",
        "vtoken",
        "x-api-key",
        "zip",
        "zipcode",
    }
)

# A name can be a secret in one place and the answer in another. An appliance
# reports what it is complaining about as a list of codes, and those are words
# it picked from a list of its own: they are the one thing a report about a
# machine misbehaving cannot do without. The code that arrives in a login is a
# credential and shares nothing with them but the name, so what a field sits
# under decides which of the two it is.
OPENLY = {
    "alert": frozenset({"code"}),
    "alerts": frozenset({"code"}),
}


def _secret(key: str, under: str) -> bool:
    """Whether a field is a secret where it turned up."""
    named = key.lower()
    return named in SECRETS and named not in OPENLY.get(under.lower(), frozenset())


def _hidden(value: Any) -> Any:
    """What a secret is replaced by.

    A note of its length where it has one, since that is what tells a token
    that arrived truncated from one that did not. Anything under a secret name
    goes whatever type it came as: a postcode and a year of birth are numbers,
    and hiding only the ones that happen to be text gives the rest away.

    Nothing is not a secret, so it stays as it is and says so.
    """
    if value is None or value == "":
        return value
    if isinstance(value, str):
        return f"<{len(value)} chars hidden>"
    return "<hidden>"


def redact(data: Any, under: str = "") -> Any:
    """Copy a structure with every secret replaced by a note of its length.

    What a field sits under travels with it, since a couple of names mean one
    thing in an appliance's report and another in a login.
    """
    if isinstance(data, dict):
        return {
            key: (
                _hidden(value) if _secret(str(key), under) else redact(value, str(key))
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        # A list does not name anything, so its members are still under
        # whatever the list itself was under.
        return [redact(item, under) for item in data]
    return data


def redact_url(url: str) -> str:
    """Hide the appliance id in a path, which names one particular machine.

    Only the segment after "appliances" can be an id, and the ones that are
    plain words there are parts of the route rather than an identifier.
    """
    parts = url.split("/")
    return "/".join(
        "<appliance id hidden>"
        if index and parts[index - 1] == "appliances" and not part.isalpha()
        else part
        for index, part in enumerate(parts)
    )


# Enough for an appliance list, which runs to twelve kilobytes and keeps what
# is worth reading at the far end of it. A shorter cut made the log useless for
# the one question it was there to answer.
MOST = 20000


def _readable(body: bytes) -> str:
    """A body fit to log: redacted if it is JSON, described if it is not."""
    if not body:
        return "empty"
    try:
        readable = json.dumps(redact(json.loads(body)))
    except ValueError:
        return f"<{len(body)} bytes that are not JSON>"
    if len(readable) <= MOST:
        return readable
    return f"{readable[:MOST]} <{len(readable) - MOST} more characters>"


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
    _LOGGER.debug("%s %s params=%s", method, redact_url(url), params)
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
        raise AegConnectionError(f"{redact_url(url)} is unreachable: {err}") from err

    _LOGGER.debug("  <- body %s", _readable(body))

    if status >= 500:
        raise AegBackendError(f"{redact_url(url)} failed with status {status}")
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError as err:
        raise AegConnectionError(
            f"{redact_url(url)} answered status {status} with a body that is not JSON"
        ) from err
