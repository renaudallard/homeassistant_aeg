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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import (
    CONF_COUNTRY,
    CONF_EMAIL,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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


@contextmanager
def _cloud(api: AsyncMock) -> Iterator[MagicMock]:
    """Stand in for the cloud, the calls and the stream alike.

    Without the second of those every test here opens a websocket to the real
    endpoint the entry names and waits on the network to refuse it.
    """
    with (
        patch("custom_components.aeg.AegApi", return_value=api),
        patch("custom_components.aeg.coordinator.AegStream", autospec=True) as stream,
    ):
        yield stream


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    with _cloud(api):
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


async def test_a_thermostat_out_of_reach_cannot_be_set(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The parts it gathers up go unavailable, and it has to go with them."""
    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["connectionState"] = "disconnected"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    climate = hass.states.get(THERMOSTAT)
    assert climate is not None and climate.state == STATE_UNAVAILABLE
    target = hass.states.get("number.clim_target_temperature")
    assert target is not None and target.state == STATE_UNAVAILABLE


async def test_the_fan_speeds_follow_the_mode_it_is_in(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """It drops TURBO from the fan speeds in its automatic and fan only modes."""
    await _setup(hass, entry, api)
    cooling = hass.states.get("select.clim_fan_speed")
    assert cooling is not None
    assert "TURBO" in cooling.attributes["options"]

    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["properties"]["reported"]["mode"] = "FANONLY"
    api.appliances.return_value = listed
    with _cloud(api):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    limited = hass.states.get("select.clim_fan_speed")
    assert limited is not None
    assert limited.attributes["options"] == ["AUTO", "HIGH", "LOW", "MIDDLE", "QUIET"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.clim_fan_speed", "option": "TURBO"},
            blocking=True,
        )


async def test_the_thermostat_offers_the_same_fan_speeds_as_the_select(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The thermostat is the same fields, so it takes the same values."""
    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["properties"]["reported"]["mode"] = "FANONLY"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    climate = hass.states.get(THERMOSTAT)
    assert climate is not None
    assert climate.attributes["fan_modes"] == ["AUTO", "HIGH", "LOW", "MIDDLE", "QUIET"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": THERMOSTAT, "fan_mode": "TURBO"},
            blocking=True,
        )
    api.send_command.assert_not_awaited()


async def test_a_fan_speed_it_will_not_change_offers_only_where_it_stands(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Drying takes no fan speed at all, so there is nothing to choose."""
    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["properties"]["reported"]["mode"] = "DRY"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    climate = hass.states.get(THERMOSTAT)
    assert climate is not None
    assert climate.attributes["fan_modes"] == ["AUTO"]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_fan_mode",
            {"entity_id": THERMOSTAT, "fan_mode": "TURBO"},
            blocking=True,
        )
    api.send_command.assert_not_awaited()


async def test_a_reading_in_fahrenheit_is_not_read_as_celsius(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The appliance describes both scales and says which is which."""
    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["properties"]["reported"]["ambientTemperatureF"] = 79.7
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    celsius = hass.states.get("sensor.clim_room_temperature")
    assert celsius is not None
    assert celsius.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS
    assert float(celsius.state) == 26.5

    # Home Assistant is set to celsius here, so the fahrenheit reading arrives
    # converted rather than as the number the appliance said.
    fahrenheit = hass.states.get("sensor.clim_room_temperature_2")
    assert fahrenheit is not None
    assert fahrenheit.attributes["unit_of_measurement"] == UnitOfTemperature.CELSIUS
    assert float(fahrenheit.state) == 26.5


async def test_a_temperature_the_appliance_words_is_not_read_as_degrees(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A field that lists what it can say holds a word, not a reading."""
    tree = json.loads((FIXTURES / "ac-capabilities.json").read_text())
    tree["comfortTemperature"] = {
        "access": "read",
        "type": "temperature",
        "values": {"COLD": {}, "WARM": {}},
    }
    api.capabilities.return_value = tree
    listed = json.loads((FIXTURES / "ac-appliances.json").read_text())
    listed[0]["properties"]["reported"]["comfortTemperature"] = "COLD"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    worded = hass.states.get("sensor.clim_comfort_temperature")
    assert worded is not None
    assert worded.state == "COLD"
    assert "unit_of_measurement" not in worded.attributes
    assert "device_class" not in worded.attributes


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
    # Whole, the way the appliance reports it and the way the number entity
    # on the same field sends it. 19.0 compares equal to 19, so the type is
    # what has to be looked at.
    assert command == {"targetTemperatureC": 19}
    assert isinstance(command["targetTemperatureC"], int)


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


async def test_turning_it_on_uses_the_command_it_has_for_that(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """This one has no ON among its modes, only a command that says it."""
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": THERMOSTAT}, blocking=True
    )
    _, command = api.send_command.await_args.args
    assert command == {"executeCommand": "ON"}


async def test_it_is_told_on_and_off_the_way_it_words_them(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A model with both words among its modes never reaches for a command."""
    tree = json.loads((FIXTURES / "ac-capabilities.json").read_text())
    tree["mode"]["values"]["ON"] = {}
    del tree["executeCommand"]
    api.capabilities.return_value = tree

    await _setup(hass, entry, api)
    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": THERMOSTAT}, blocking=True
    )
    _, command = api.send_command.await_args.args
    assert command == {"mode": "ON"}


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
