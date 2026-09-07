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
from typing import Any

import aiohttp

from .const import CONNECT_TIMEOUT, REQUEST_TIMEOUT
from .errors import AegBackendError, AegConnectionError

TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)


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
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AegConnectionError(f"{url} is unreachable: {err}") from err

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
