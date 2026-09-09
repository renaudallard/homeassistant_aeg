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

"""Tests for how often the account is asked, given a stream.

Polling is the safety net under the stream. It only eases off once the stream
has proved it carries something, because a connection the cloud accepts and
then says nothing on would otherwise leave an appliance looked at once every
ten minutes.
"""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.aeg.capability import Capability
from custom_components.aeg.const import DOMAIN
from custom_components.aeg.coordinator import (
    SCAN_INTERVAL,
    SCAN_INTERVAL_STREAMING,
    AegCoordinator,
    Appliance,
)


def _coordinator(hass: HomeAssistant) -> AegCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return AegCoordinator(hass, entry, AsyncMock(), MagicMock())


class _Socket:
    """A connection that stays open and says nothing."""

    def __aiter__(self) -> "_Socket":
        return self

    async def __anext__(self) -> Any:
        await asyncio.sleep(3600)
        raise StopAsyncIteration


class _Connection:
    async def __aenter__(self) -> _Socket:
        return _Socket()

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _Cloud:
    """A cloud that accepts a connection and holds it open."""

    def __init__(self) -> None:
        self.opened = 0

    def ws_connect(self, url: str, **kwargs: Any) -> _Connection:
        self.opened += 1
        return _Connection()


async def test_the_entry_owns_the_stream(hass: HomeAssistant) -> None:
    """It has to go when the entry does, so the entry is what holds it.

    Reaching into the entry is the only way to see whose task it is, and whose
    it is decides whether anything cancels it when the entry unloads.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.authorization = AsyncMock(return_value="Bearer a-token")
    api.seconds_until_renewal = MagicMock(return_value=43200.0)
    cloud = _Cloud()
    coordinator = AegCoordinator(hass, entry, api, cloud)  # type: ignore[arg-type]
    coordinator.data = {"an-appliance": MagicMock()}

    coordinator.start_stream("wss://ws.eu.ocp.electrolux.one")
    await asyncio.sleep(0.05)
    assert cloud.opened == 1
    assert len(entry._background_tasks) == 1

    await coordinator.stop_stream()
    assert not entry._background_tasks


async def test_opening_a_stream_is_not_reason_enough_to_ease_off(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(hass)
    assert coordinator.update_interval == SCAN_INTERVAL

    coordinator._streaming(True)
    assert coordinator.update_interval == SCAN_INTERVAL


async def test_being_told_something_is(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass)
    coordinator.data = {}
    coordinator._streaming(True)

    message: dict[str, Any] = {
        "Payload": {
            "Appliances": [
                {
                    "ApplianceId": "an-appliance",
                    "Metrics": [{"Name": "doorState", "Value": "OPEN"}],
                }
            ]
        }
    }
    # Nothing on the account matches, so nothing was learned.
    coordinator._pushed(message)
    assert coordinator.update_interval == SCAN_INTERVAL

    appliance = MagicMock()
    appliance.reported = {"doorState": "CLOSED"}
    appliance.capabilities = []
    coordinator.data = {"an-appliance": appliance}
    coordinator._pushed(message)
    assert coordinator.update_interval == SCAN_INTERVAL_STREAMING


async def test_a_stream_that_drops_puts_it_back(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass)
    coordinator.update_interval = SCAN_INTERVAL_STREAMING

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._streaming(False)
        await hass.async_block_till_done()

    assert coordinator.update_interval == SCAN_INTERVAL
    # The look already scheduled is ten minutes out, so shortening the
    # interval on its own leaves the appliance unwatched until it happens.
    asked.assert_called_once()


async def test_a_stream_that_drops_while_polling_asks_for_nothing(
    hass: HomeAssistant,
) -> None:
    """Every reconnect says the stream dropped, and most of them change nothing."""
    coordinator = _coordinator(hass)

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._streaming(False)
        await hass.async_block_till_done()

    assert coordinator.update_interval == SCAN_INTERVAL
    asked.assert_not_called()


def _washing(state: str, time_to_end: int) -> Appliance:
    """A machine that says what it is doing and how long is left of it."""
    return Appliance(
        id="an-appliance",
        name="Lave-linge",
        model="WM",
        info={},
        capabilities=[
            Capability(path="applianceState", access="read", kind="string"),
            Capability(path="timeToEnd", access="read", kind="number"),
        ],
        reported={"applianceState": state, "timeToEnd": time_to_end},
        connected=True,
        overrides={},
    )


def _said(time_to_end: int) -> dict[str, Any]:
    return {
        "Payload": {
            "Appliances": [
                {
                    "ApplianceId": "an-appliance",
                    "Metrics": [{"Name": "timeToEnd", "Value": time_to_end}],
                }
            ]
        }
    }


async def _wait_out_the_end(hass: HomeAssistant) -> None:
    """Let the moment the cycle should have finished go by."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=90))
    await hass.async_block_till_done()


async def test_it_looks_again_when_a_cycle_should_have_ended(
    hass: HomeAssistant,
) -> None:
    """The cloud goes quiet about the wash while the stream stays busy."""
    coordinator = _coordinator(hass)
    coordinator.data = {"an-appliance": _washing("RUNNING", 120)}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._pushed(_said(30))
        # Streaming, so the next look of its own accord is ten minutes out.
        assert coordinator.update_interval == SCAN_INTERVAL_STREAMING
        await _wait_out_the_end(hass)

    asked.assert_called_once()


async def test_a_machine_that_is_not_running_is_not_waited_on(
    hass: HomeAssistant,
) -> None:
    """A finished wash puts the next programme's length where the time left was."""
    coordinator = _coordinator(hass)
    coordinator.data = {"an-appliance": _washing("END_OF_CYCLE", 120)}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._pushed(_said(30))
        await _wait_out_the_end(hass)

    asked.assert_not_called()


async def test_a_machine_with_a_while_to_go_is_not_waited_on(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(hass)
    coordinator.data = {"an-appliance": _washing("RUNNING", 3600)}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._pushed(_said(1800))
        await _wait_out_the_end(hass)

    asked.assert_not_called()


async def test_counting_down_to_zero_books_one_look_and_not_sixty(
    hass: HomeAssistant,
) -> None:
    """Every second of the last minute would otherwise arrange its own."""
    coordinator = _coordinator(hass)
    coordinator.data = {"an-appliance": _washing("RUNNING", 120)}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        for left in range(50, 0, -1):
            coordinator._pushed(_said(left))
        await _wait_out_the_end(hass)

    asked.assert_called_once()


async def test_nothing_is_waited_on_once_the_entry_has_gone(
    hass: HomeAssistant,
) -> None:
    """An arranged look outliving its entry would ask about an account that has."""
    coordinator = _coordinator(hass)
    coordinator.data = {"an-appliance": _washing("RUNNING", 120)}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as asked:
        coordinator._pushed(_said(30))
        coordinator.stop_waiting()
        await _wait_out_the_end(hass)

    asked.assert_not_called()
