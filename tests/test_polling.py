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

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.aeg.coordinator import (
    SCAN_INTERVAL,
    SCAN_INTERVAL_STREAMING,
    AegCoordinator,
)


def _coordinator(hass: HomeAssistant) -> AegCoordinator:
    entry = MagicMock()
    entry.entry_id = "an-entry"
    return AegCoordinator(hass, entry, AsyncMock(), MagicMock())


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
