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

"""Live updates pushed by the cloud.

Polling means a cycle can finish half a minute before anyone hears about it.
The cloud will push instead, over a websocket that carries only what changed:
one appliance, and the fields of it that moved.

The connection is told which appliances to watch when it opens, and carries the
user token, so it is opened again whenever it drops or the token turns over.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# The cloud drops a connection that says nothing for ten minutes.
HEARTBEAT = 300.0
RECONNECT_DELAY = 5.0
# Something is wrong rather than merely unlucky, so wait longer.
RECONNECT_DELAY_UNEXPECTED = 30.0


class AegStream:
    """Watches one account's appliances for as long as it is running."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        authorization: Callable[[], Any],
        appliance_ids: list[str],
        on_message: Callable[[dict[str, Any]], None],
        on_connected: Callable[[bool], None],
    ) -> None:
        self._session = session
        self._url = url
        self._authorization = authorization
        self._appliance_ids = appliance_ids
        self._on_message = on_message
        self._on_connected = on_connected
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None and self._appliance_ids:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": await self._authorization(),
            "appliances": json.dumps(
                [{"applianceId": identifier} for identifier in self._appliance_ids]
            ),
            "version": "2",
        }

    async def _run(self) -> None:
        while True:
            delay = RECONNECT_DELAY
            try:
                await self._listen()
            except asyncio.CancelledError:
                raise
            except aiohttp.ClientError as err:
                _LOGGER.debug("the stream dropped: %s", err)
            except Exception:
                _LOGGER.exception("the stream failed unexpectedly")
                delay = RECONNECT_DELAY_UNEXPECTED
            finally:
                self._on_connected(False)
            await asyncio.sleep(delay)

    async def _listen(self) -> None:
        async with self._session.ws_connect(
            self._url, headers=await self._headers(), heartbeat=HEARTBEAT
        ) as socket:
            _LOGGER.debug("watching %d appliances", len(self._appliance_ids))
            self._on_connected(True)
            async for message in socket:
                if message.type is aiohttp.WSMsgType.TEXT:
                    self._on_message(message.json())
                elif message.type is aiohttp.WSMsgType.ERROR:
                    raise aiohttp.ClientError("the stream reported an error")
                else:
                    break


def merge(reported: dict[str, Any], name: str, value: Any) -> None:
    """Fold one pushed field into the state we hold.

    A push carries only what changed, and for a group of fields it carries only
    the members that moved, so a group has to be merged rather than replaced.
    """
    held = reported.get(name)
    if isinstance(value, dict) and isinstance(held, dict):
        for key, nested in value.items():
            merge(held, key, nested)
        return
    reported[name] = value


def apply(message: dict[str, Any], state: dict[str, dict[str, Any]]) -> set[str]:
    """Apply a pushed message, and say whose state it touched."""
    touched: set[str] = set()
    payload = message.get("Payload") or {}
    for entry in payload.get("Appliances") or []:
        appliance_id = str(entry.get("ApplianceId") or "")
        reported = state.get(appliance_id)
        if reported is None:
            continue
        for metric in entry.get("Metrics") or []:
            name = metric.get("Name")
            if isinstance(name, str):
                merge(reported, name, metric.get("Value"))
                touched.add(appliance_id)
    return touched
