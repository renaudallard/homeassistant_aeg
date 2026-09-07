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
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

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
    # How long the token has left is asked for, not awaited.
    mock.seconds_until_renewal = MagicMock(return_value=43200.0)
    return mock


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    with patch("custom_components.aeg.AegApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _again(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    """Set the entry up a second time, with the cloud still stood in for."""
    with patch("custom_components.aeg.AegApi", return_value=api):
        await hass.config_entries.async_reload(entry.entry_id)
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


async def test_an_account_that_answers_with_nothing_takes_nothing_down(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Knowing of nothing is not the same as knowing there is nothing."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    before = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert before

    # The account answers with an empty list, for a moment or for good.
    api.appliances.return_value = []
    await _again(hass, entry, api)

    after = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert after == before


async def test_the_entities_built_on_a_field_are_kept_with_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A clock, a finishing time and a button are not fields of their own.

    Home Assistant remembers an entity it has been told to forget and gives it
    back its own id if it returns, so getting this wrong costs less than it
    might. It is still wrong.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    kept = {
        e.unique_id.split("-", 1)[1]
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert "timeToEnd-formatted" in kept
    assert "timeToEnd-at" in kept
    assert "executeCommand-START" in kept

    # An entry taken out of the register and put back is a different entry,
    # and takes whatever had been done to it with it, so setting up again has
    # to leave the ones it already has alone.
    was = {
        e.unique_id: e.id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    await _again(hass, entry, api)
    now = {
        e.unique_id: e.id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert now == was


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


async def test_a_quiet_machine_reports_no_problem(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An empty list of alerts is an answer, not a missing value."""
    await _setup(hass, entry, api)
    state = hass.states.get("binary_sensor.lave_linge_alerts")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["alerts"] == []
    assert state.attributes["device_class"] == "problem"


async def test_a_complaining_machine_says_what_is_wrong(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["alerts"] = ["DOOR", "UNBALANCED_LAUNDRY"]
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    state = hass.states.get("binary_sensor.lave_linge_alerts")
    assert state is not None
    assert state.state == "on"
    assert state.attributes["alerts"] == ["DOOR", "UNBALANCED_LAUNDRY"]


async def test_a_richer_alert_is_not_thrown_away(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Not every model has to report a plain code."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["alerts"] = [{"code": "WATER_LEAK"}]
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    state = hass.states.get("binary_sensor.lave_linge_alerts")
    assert state is not None
    assert state.state == "on"
    assert state.attributes["alerts"] == ["WATER_LEAK"]


async def test_a_length_of_time_is_also_offered_as_a_clock(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 4145
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    seconds = hass.states.get("sensor.lave_linge_time_to_end")
    assert seconds is not None
    assert seconds.state == "4145"
    assert seconds.attributes["device_class"] == "duration"

    clock = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert clock is not None
    hours, minutes, seconds_left = (int(part) for part in clock.state.split(":"))
    # It counts down from the moment the appliance said it, so a moment can
    # have gone by while the entity was being set up.
    assert 4135 <= hours * 3600 + minutes * 60 + seconds_left <= 4145


async def test_the_finish_is_fixed_to_a_moment(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Home Assistant counts down to a timestamp without being told to."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    api.appliances.return_value = listed

    before = dt_util.utcnow()
    await _setup(hass, entry, api)
    after = dt_util.utcnow()

    finishes = hass.states.get("sensor.lave_linge_finishes_at")
    assert finishes is not None
    assert finishes.attributes["device_class"] == "timestamp"
    at = dt_util.parse_datetime(finishes.state)
    assert at is not None
    # An hour from when it was read, to the second.
    assert (
        abs((at - (before + timedelta(seconds=3600))).total_seconds())
        <= (after - before).total_seconds() + 1
    )


async def test_the_finish_moves_when_the_machine_changes_its_mind(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Picking another programme changes how long is left, so it moves."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    first = hass.states.get("sensor.lave_linge_finishes_at")
    assert first is not None
    was = dt_util.parse_datetime(first.state)
    assert was is not None

    # A shorter programme is chosen and the cloud says so on the next look.
    shorter = _fixture("wm-appliances")
    shorter[0]["properties"]["reported"]["timeToEnd"] = 1200
    shorter[0]["properties"]["reported"]["userSelections"]["programUID"] = (
        "QUICK_20_MIN_PR_20MIN3KG"
    )
    api.appliances.return_value = shorter
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    second = hass.states.get("sensor.lave_linge_finishes_at")
    assert second is not None
    now = dt_util.parse_datetime(second.state)
    assert now is not None
    assert now < was
    assert abs((now - dt_util.utcnow()).total_seconds() - 1200) <= 2


async def test_the_finish_moves_when_the_cloud_pushes_a_new_time(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The same holds for a change that arrives over the websocket."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    coordinator = entry.runtime_data.coordinator
    appliance_id = next(iter(coordinator.data))
    coordinator._pushed(
        {
            "Payload": {
                "Appliances": [
                    {
                        "ApplianceId": appliance_id,
                        "Metrics": [{"Name": "timeToEnd", "Value": 900}],
                    }
                ]
            }
        }
    )
    await hass.async_block_till_done()

    finishes = hass.states.get("sensor.lave_linge_finishes_at")
    assert finishes is not None
    at = dt_util.parse_datetime(finishes.state)
    assert at is not None
    assert abs((at - dt_util.utcnow()).total_seconds() - 900) <= 2


async def test_a_machine_with_nothing_running_has_no_finish(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    assert _fixture("wm-appliances")[0]["properties"]["reported"]["timeToEnd"] == -1
    finishes = hass.states.get("sensor.lave_linge_finishes_at")
    assert finishes is not None
    assert finishes.state == "unknown"


async def test_only_the_time_left_gets_a_finish(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A time the machine was set to is not counting down to anything."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    ending = {
        entity.unique_id.split("-", 1)[1]
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.unique_id.endswith("-at")
    }
    assert ending == {"timeToEnd-at"}


async def test_a_time_the_machine_does_not_have_reads_as_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine says -1 for the end of a cycle it is not running."""
    await _setup(hass, entry, api)
    assert _fixture("wm-appliances")[0]["properties"]["reported"]["timeToEnd"] == -1
    clock = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert clock is not None
    assert clock.state == "unknown"


async def test_a_numbered_level_reads_as_its_number(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Water hardness is one scale of seven, whatever it calls each step.

    This machine names the first three and numbers the rest, and the numbered
    ones land on their own place, so the whole of it reads as one to seven.
    """
    await _setup(hass, entry, api)
    hardness = hass.states.get("select.lave_linge_water_hardness")
    assert hardness is not None
    assert hardness.attributes["options"] == ["1", "2", "3", "4", "5", "6", "7"]
    assert hardness.state == "4"


async def test_a_numbered_level_is_sent_back_as_the_appliance_names_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.lave_linge_water_hardness", "option": "6"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"waterHardness": "STEP_6"}


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
