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

"""Loading a real appliance into Home Assistant.

The fixtures are a washing machine on a real account, with the identifiers
taken out. Nothing here says what a washing machine is: the entities come from
what the appliance says about itself, so this is the check that the reading of
that description holds up against a real one.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


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
    mock.appliances.return_value = _fixture("wm-appliances")
    mock.capabilities.return_value = _fixture("wm-capabilities")
    return mock


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    with patch("custom_components.aeg.AegApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_the_appliance_loads(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    # Capabilities describe the model, not its state, so they are read once.
    api.capabilities.assert_awaited_once()


async def test_it_becomes_one_device_with_entities_on_every_platform(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert entities

    devices = {entity.device_id for entity in entities}
    assert len(devices) == 1, "one appliance is one device"

    platforms = {entity.domain for entity in entities}
    assert platforms == {
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    }


async def test_the_wash_is_shown_and_the_housekeeping_is_not(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine describes far more than anyone wants to look at."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)

    shown = [e for e in entities if not e.disabled]
    hidden = [e for e in entities if e.disabled]
    assert shown, "something has to be visible"
    assert hidden, "the maintenance counters should not be"
    assert len(shown) < len(hidden) + len(shown)

    by_id = {e.unique_id: e for e in entities}
    # What someone actually wants: the programme, and the door.
    assert "userSelections/programUID" in str(list(by_id))
    for hidden_field in by_id:
        if "applianceCareAndMaintenance" in hidden_field:
            assert by_id[hidden_field].disabled, hidden_field


async def test_every_entity_survives_being_added(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An entity that raises while being added is dropped with a log line.

    Checking a handful of entities hides that, so check that every one of them
    reached a state.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    expected = [
        entity
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if not entity.disabled
    ]
    assert expected
    missing = [e.entity_id for e in expected if hass.states.get(e.entity_id) is None]
    assert not missing, f"entities that failed to load: {missing}"


async def test_nothing_is_made_for_a_field_the_machine_does_not_have(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A tree covers a range of models and lists fields this one lacks."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    made = {
        e.unique_id.split("-", 1)[1]
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    # This machine never reports the stored personalisation, only the live one.
    assert "userSelections/analogTemperature" in made
    assert not [path for path in made if path.startswith("cyclePersonalization/")]


async def test_what_an_earlier_version_left_behind_is_taken_away(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Entities already in the register outlive a change of mind about them."""
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "select",
        DOMAIN,
        "an-appliance-cyclePersonalization/analogTemperature",
        config_entry=entry,
        suggested_object_id="lave_linge_stale",
    )
    assert registry.async_get(stale.entity_id) is not None

    await _setup(hass, entry, api)
    assert registry.async_get(stale.entity_id) is None


async def test_readings_carry_the_reported_value(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = {
        e.unique_id.split("-", 1)[1]: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    door = hass.states.get(entities["doorState"])
    assert door is not None and door.state == "OPEN"

    programme = hass.states.get(entities["userSelections/programUID"])
    assert programme is not None
    assert programme.state == "COTTON_PR_ECO40-60"
    assert "COTTON_PR_ECO40-60" in programme.attributes["options"]

    temperature = hass.states.get(entities["userSelections/analogTemperature"])
    assert temperature is not None and temperature.state == "40_CELSIUS"


async def test_a_nested_field_is_sent_back_nested(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Capabilities write the path into the key; the appliance wants it nested."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = {
        e.unique_id.split("-", 1)[1]: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    await hass.services.async_call(
        "select",
        "select_option",
        {
            "entity_id": entities["userSelections/analogTemperature"],
            "option": "60_CELSIUS",
        },
        blocking=True,
    )
    api.send_command.assert_awaited_once()
    _, command = api.send_command.await_args.args
    assert command == {"userSelections": {"analogTemperature": "60_CELSIUS"}}
