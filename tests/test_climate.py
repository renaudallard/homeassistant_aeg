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

"""Tests for gathering an air conditioner into a thermostat.

The capability tree is a real one, shipped inside the app for an air
conditioner. The state beside it is made up, since there is no such appliance
here to ask, so what these check is the reading of the tree rather than that an
air conditioner does what it is told.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aeg.const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_WS_URL,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
THERMOSTAT = "climate.clim"


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="someone@example.com",
        data={
            CONF_EMAIL: "someone@example.com",
            CONF_COUNTRY: "BE",
            CONF_BASE_URL: "https://api.eu.ocp.electrolux.one",
            CONF_WS_URL: "wss://ws.eu.ocp.electrolux.one",
            CONF_ACCESS_TOKEN: "an-access-token",
            CONF_REFRESH_TOKEN: "a-refresh-token",
            CONF_EXPIRES_AT: 4102444800.0,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def api() -> AsyncMock:
    mock = AsyncMock()
    mock.appliances.return_value = json.loads(
        (FIXTURES / "ac-appliances.json").read_text()
    )
    mock.capabilities.return_value = json.loads(
        (FIXTURES / "ac-capabilities.json").read_text()
    )
    mock.seconds_until_renewal = lambda: 43200.0
    return mock


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    with patch("custom_components.aeg.AegApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_an_air_conditioner_becomes_a_thermostat(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    climate = hass.states.get(THERMOSTAT)
    assert climate is not None
    assert climate.state == HVACMode.COOL
    assert climate.attributes["temperature"] == 22.0
    assert climate.attributes["current_temperature"] == 26.5
    assert climate.attributes["min_temp"] == 16.0
    assert climate.attributes["max_temp"] == 30.0
    assert climate.attributes["fan_mode"] == "AUTO"


async def test_only_the_ways_of_running_it_knows_are_offered(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """It offers AUTOCLEAN and SMART as well, which mean nothing here."""
    await _setup(hass, entry, api)
    climate = hass.states.get(THERMOSTAT)
    assert climate is not None
    assert set(climate.attributes["hvac_modes"]) == {
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.OFF,
    }


async def test_a_washing_machine_is_not_a_thermostat(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    api.appliances.return_value = json.loads(
        (FIXTURES / "wm-appliances.json").read_text()
    )
    api.capabilities.return_value = json.loads(
        (FIXTURES / "wm-capabilities.json").read_text()
    )
    await _setup(hass, entry, api)
    assert not [state for state in hass.states.async_all() if state.domain == "climate"]


async def test_setting_the_temperature_says_so_in_degrees(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": THERMOSTAT, "temperature": 19},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"targetTemperatureC": 19.0}


async def test_choosing_a_way_of_running_it_says_so_in_its_own_word(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": THERMOSTAT, "hvac_mode": HVACMode.DRY},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"mode": "DRY"}


async def test_turning_it_off_uses_the_mode_it_has_for_that(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """This one has an off mode, so there is no need to command it off."""
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": THERMOSTAT}, blocking=True
    )
    _, command = api.send_command.await_args.args
    assert command == {"mode": "OFF"}


async def test_the_fan_and_the_swing_are_sent_as_they_come(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate",
        "set_fan_mode",
        {"entity_id": THERMOSTAT, "fan_mode": "TURBO"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"fanSpeedSetting": "TURBO"}

    await hass.services.async_call(
        "climate",
        "set_swing_mode",
        {"entity_id": THERMOSTAT, "swing_mode": "ON"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"verticalSwing": "ON"}
