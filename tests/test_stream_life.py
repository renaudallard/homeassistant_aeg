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

"""Tests for how long a stream stays open.

A connection is opened with a token and keeps it for as long as it lives, so it
has to be opened again before that token expires. Waiting for the cloud to
object would mean trusting it to notice, and a stream that is quietly ignored
looks exactly like a quiet appliance.
"""

import asyncio
import logging
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.aeg import websocket
from custom_components.aeg.websocket import AegStream


class _Silence:
    """A socket that stays open and never says anything."""

    def __aiter__(self) -> "_Silence":
        return self

    async def __anext__(self) -> Any:
        await asyncio.sleep(3600)
        raise StopAsyncIteration


class _Connection:
    def __init__(self, socket: _Silence) -> None:
        self._socket = socket

    async def __aenter__(self) -> _Silence:
        return self._socket

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _Session:
    """Counts how many times a connection was asked for."""

    def __init__(self) -> None:
        self.opened: list[dict[str, str]] = []

    def ws_connect(self, url: str, **kwargs: Any) -> _Connection:
        self.opened.append(kwargs.get("headers") or {})
        return _Connection(_Silence())


async def _authorization() -> str:
    return "Bearer a-token"


async def test_it_opens_again_when_the_token_is_running_out() -> None:
    session = _Session()
    stream = AegStream(
        session,  # type: ignore[arg-type]
        "wss://ws.eu.ocp.electrolux.one",
        _authorization,
        lambda: 0.0,
        ["an-appliance"],
        lambda message: None,
        lambda connected: None,
    )
    with (
        patch.object(websocket, "MINIMUM_LIFE", 0.01),
        patch.object(websocket, "RECONNECT_DELAY", 0.01),
    ):
        stream.start()
        await asyncio.sleep(0.2)
        await stream.stop()

    # Several short lives rather than one that outlived its token.
    assert len(session.opened) > 1
    assert all(
        headers["Authorization"] == "Bearer a-token" for headers in session.opened
    )


async def test_it_stays_open_while_the_token_is_good() -> None:
    session = _Session()
    stream = AegStream(
        session,  # type: ignore[arg-type]
        "wss://ws.eu.ocp.electrolux.one",
        _authorization,
        lambda: 3600.0,
        ["an-appliance"],
        lambda message: None,
        lambda connected: None,
    )
    stream.start()
    await asyncio.sleep(0.2)
    await stream.stop()

    assert len(session.opened) == 1


async def test_it_says_which_appliances_to_watch() -> None:
    session = _Session()
    stream = AegStream(
        session,  # type: ignore[arg-type]
        "wss://ws.eu.ocp.electrolux.one",
        _authorization,
        lambda: 3600.0,
        ["one", "two"],
        lambda message: None,
        lambda connected: None,
    )
    stream.start()
    await asyncio.sleep(0.05)
    await stream.stop()

    assert session.opened[0]["appliances"] == (
        '[{"applianceId": "one"}, {"applianceId": "two"}]'
    )
    assert session.opened[0]["version"] == "2"


class _Broken:
    """A session that cannot open a connection at all."""

    def __init__(self) -> None:
        self.tried = 0

    def ws_connect(self, url: str, **kwargs: Any) -> _Connection:
        self.tried += 1
        raise RuntimeError("no route to the cloud")


async def test_a_stream_that_never_works_says_so_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A URL kept from an account that has moved would fill the log."""
    session = _Broken()
    stream = AegStream(
        session,  # type: ignore[arg-type]
        "wss://ws.eu.ocp.electrolux.one",
        _authorization,
        lambda: 43200.0,
        ["an-appliance"],
        lambda message: None,
        lambda connected: None,
    )
    with (
        caplog.at_level(logging.ERROR, logger="custom_components.aeg.websocket"),
        patch.object(websocket, "RECONNECT_DELAY_UNEXPECTED", 0.01),
    ):
        stream.start()
        await asyncio.sleep(0.2)
        await stream.stop()

    assert session.tried > 1
    complaints = [
        record for record in caplog.records if record.levelno >= logging.ERROR
    ]
    assert len(complaints) == 1
