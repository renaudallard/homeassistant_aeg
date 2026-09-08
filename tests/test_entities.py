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

import copy
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
    async_fire_time_changed,
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


async def test_it_asks_for_the_capabilities_once_and_keeps_them(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Fifty kilobytes describing a model that has not changed."""
    await _setup(hass, entry, api)
    assert api.capabilities.await_count == 1

    await _again(hass, entry, api)
    # The appliance published the same hash, so there was nothing to fetch.
    assert api.capabilities.await_count == 1


async def test_it_asks_again_when_the_appliance_says_it_has_changed(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    assert api.capabilities.await_count == 1

    changed = _fixture("wm-appliances")
    changed[0]["properties"]["reported"]["applianceInfo"]["capabilityHash"] = (
        "a-new-one"
    )
    api.appliances.return_value = changed
    await _again(hass, entry, api)
    assert api.capabilities.await_count == 2


async def test_an_appliance_that_says_nothing_about_its_capabilities_is_asked(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """No hash is no promise, so there is nothing to trust."""
    quiet = _fixture("wm-appliances")
    del quiet[0]["properties"]["reported"]["applianceInfo"]["capabilityHash"]
    api.appliances.return_value = quiet

    await _setup(hass, entry, api)
    await _again(hass, entry, api)
    assert api.capabilities.await_count == 2


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
        Platform.UPDATE,
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
    appliance = _fixture("wm-appliances")[0]["applianceId"]
    stale = registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{appliance}-aFieldNothingDescribesAnyMore",
        config_entry=entry,
        suggested_object_id="lave_linge_stale",
    )
    assert registry.async_get(stale.entity_id) is not None

    await _setup(hass, entry, api)
    assert registry.async_get(stale.entity_id) is None


async def test_a_field_never_reported_is_still_taken_away(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The machine describes a whole group of settings it does not have."""
    registry = er.async_get(hass)
    appliance = _fixture("wm-appliances")[0]["applianceId"]
    stale = registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{appliance}-cyclePersonalization/analogTemperature",
        config_entry=entry,
        suggested_object_id="lave_linge_never_reported",
    )

    await _setup(hass, entry, api)
    assert registry.async_get(stale.entity_id) is None


async def test_an_appliance_that_has_gone_quiet_keeps_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine at the end of a cycle turns itself off.

    Starting up while it is off used to read its silence as a machine that
    had never had any of those fields, and take every one of them away.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    before = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert before

    quiet = _fixture("wm-appliances")
    quiet[0]["properties"]["reported"] = {}
    quiet[0]["connectionState"] = "disconnected"
    api.appliances.return_value = quiet
    await _again(hass, entry, api)

    after = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert after == before


async def test_a_group_of_settings_going_missing_takes_nothing_down(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Reachable, talking, and saying nothing about the wash settings."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    before = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    partial = _fixture("wm-appliances")
    del partial[0]["properties"]["reported"]["userSelections"]
    api.appliances.return_value = partial
    await _again(hass, entry, api)

    after = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert after == before


async def test_a_failed_setup_does_not_leave_the_stream_open(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An entry that did not load has no business holding a connection open."""
    with (
        patch("custom_components.aeg.AegApi", return_value=api),
        patch("custom_components.aeg.coordinator.AegStream", autospec=True) as stream,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            side_effect=RuntimeError("a platform did not load"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    stream.return_value.start.assert_called_once()
    stream.return_value.stop.assert_awaited_once()


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


async def test_an_appliance_a_listing_left_out_keeps_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """One appliance missing is not the account saying it has gone."""
    both = _fixture("wm-appliances")
    second = copy.deepcopy(both[0])
    second["applianceId"] = "a-second-machine"
    both.append(second)
    api.appliances.return_value = both
    await _setup(hass, entry, api)

    registry = er.async_get(hass)
    before = {
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith("a-second-machine-")
    }
    assert before

    # The account answers with the other machine and nothing else.
    api.appliances.return_value = _fixture("wm-appliances")
    await _again(hass, entry, api)

    after = {
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith("a-second-machine-")
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


async def test_it_says_what_firmware_the_appliance_is_running(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    installed = firmware.attributes["installed_version"]
    assert installed
    # Its network unit is doing nothing, so what it runs is all there is.
    assert firmware.attributes["latest_version"] == installed
    assert firmware.state == "off"


async def test_an_update_in_hand_is_not_hidden(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The appliance never says which version is coming, only that one is."""
    listed = _fixture("wm-appliances")
    network = listed[0]["properties"]["reported"]["networkInterface"]
    network["otaState"] = "READY_TO_UPDATE"
    network["niuSwUpdateCurrentDescription"] = "A23642207A-S00010202A"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.attributes["latest_version"] == "A23642207A-S00010202A"
    assert firmware.state == "on"
    assert firmware.attributes["in_progress"] is False


async def test_an_update_under_way_says_so(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["networkInterface"]["otaState"] = (
        "FW_UPDATE_IN_PROGRESS"
    )
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.attributes["in_progress"] is True


async def test_an_appliance_that_says_nothing_about_firmware_gets_no_entity(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    del listed[0]["properties"]["reported"]["networkInterface"]["otaState"]
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    assert hass.states.get("update.lave_linge_firmware") is None


async def test_an_appliance_off_the_network_says_so(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Everything else goes quiet, so one entity has to stay and explain."""
    listed = _fixture("wm-appliances")
    listed[0]["connectionState"] = "disconnected"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    connection = hass.states.get("binary_sensor.lave_linge_connection")
    assert connection is not None
    assert connection.state == "off"
    assert connection.attributes["device_class"] == "connectivity"

    # What it last said is still worth reading, which is the point of
    # looking after a wash has finished.
    door = hass.states.get("sensor.lave_linge_door")
    assert door is not None
    assert door.state == "OPEN"

    # Setting anything on it is not, since it cannot be reached.
    hardness = hass.states.get("select.lave_linge_water_hardness")
    assert hardness is not None
    assert hardness.state == "unavailable"


async def test_a_wash_that_has_finished_can_still_be_looked_at(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine turns itself off and drops off the network."""
    listed = _fixture("wm-appliances")
    listed[0]["connectionState"] = "disconnected"
    listed[0]["properties"]["reported"]["applianceState"] = "END_OF_CYCLE"
    listed[0]["properties"]["reported"]["totalWashCyclesCount"] = 42
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    state = hass.states.get("sensor.lave_linge_state")
    assert state is not None
    assert state.state == "END_OF_CYCLE"
    counted = hass.states.get("sensor.lave_linge_washes_run")
    assert counted is not None
    assert counted.state == "42"


async def test_a_finished_wash_can_still_be_looked_at(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine turns itself off and drops off the network."""
    listed = _fixture("wm-appliances")
    listed[0]["connectionState"] = "disconnected"
    listed[0]["properties"]["reported"]["applianceState"] = "END_OF_CYCLE"
    listed[0]["properties"]["reported"]["totalWashCyclesCount"] = 42
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    state = hass.states.get("sensor.lave_linge_state")
    assert state is not None
    assert state.state == "END_OF_CYCLE"
    counted = hass.states.get("sensor.lave_linge_washes_run")
    assert counted is not None
    assert counted.state == "42"


async def test_a_machine_that_has_finished_does_not_count_anything_down(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """It puts the length of the programme it is set to where the time left was.

    Counting that down would show a wash nobody has started, and a finishing
    time for one too.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["applianceState"] = "END_OF_CYCLE"
    listed[0]["properties"]["reported"]["timeToEnd"] = 9000
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 1045.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()

    # Two and a half hours, standing still.
    standing = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert standing is not None
    assert standing.state == "02:30:00"

    finishes = hass.states.get("sensor.lave_linge_finishes_at")
    assert finishes is not None
    assert finishes.state == "unknown"


async def test_a_reachable_appliance_says_that_too(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    connection = hass.states.get("binary_sensor.lave_linge_connection")
    assert connection is not None
    assert connection.state == "on"


async def test_the_connection_is_not_mistaken_for_something_stale(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """It is not a field of the appliance, so it has to be kept on purpose."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    await _again(hass, entry, api)
    kept = {
        e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert any(unique.endswith("-connection") for unique in kept)


async def test_a_field_worth_naming_gets_a_name(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An appliance calls its spin speed userSelections/analogSpinSpeed."""
    await _setup(hass, entry, api)
    spin = hass.states.get("select.lave_linge_spin_speed")
    assert spin is not None
    assert spin.attributes["friendly_name"] == "Lave-linge Spin speed"


async def test_a_field_nobody_has_named_still_gets_one(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Worked out from the field's own name, which is better than nothing."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    named = {
        entity.unique_id.split("-", 1)[1]: entity.original_name
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert named["waterHardness"] == "Water hardness"
    # A command is named for the field and the command, since nothing has been
    # written for either.
    assert named["executeCommand-START"] == "Execute command START"


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


async def test_what_went_wrong_outlives_the_machine_going_quiet(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The moment someone looks is the moment after the machine turned off."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["alerts"] = ["UNBALANCED_LAUNDRY"]
    listed[0]["connectionState"] = "disconnected"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    state = hass.states.get("binary_sensor.lave_linge_alerts")
    assert state is not None
    assert state.state == "on"
    assert state.attributes["alerts"] == ["UNBALANCED_LAUNDRY"]
    # The one entity that is meant to say the appliance has gone.
    connection = hass.states.get("binary_sensor.lave_linge_connection")
    assert connection is not None and connection.state == "off"


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
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
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


async def test_the_clock_ticks_down_between_updates(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The cloud mentions the time left now and then, not every second."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        started = hass.states.get("sensor.lave_linge_time_to_end_formatted")
        assert started is not None
        assert started.state == "01:00:00"

        for elapsed, expected in ((1.0, "00:59:59"), (45.0, "00:59:15")):
            clock.monotonic.return_value = 1000.0 + elapsed
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
            await hass.async_block_till_done()
            ticked = hass.states.get("sensor.lave_linge_time_to_end_formatted")
            assert ticked is not None
            assert ticked.state == expected


async def test_the_clock_does_not_drift_when_the_programme_changes(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A shorter cycle is picked, and the clock is on the new time at once.

    Not a minute later, and not somewhere between the two: the figure that
    arrives replaces the one being counted from.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)

        # Half a minute of counting down on the old programme.
        clock.monotonic.return_value = 1030.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
        counting = hass.states.get("sensor.lave_linge_time_to_end_formatted")
        assert counting is not None
        assert counting.state == "00:59:30"

        # A shorter programme, and the cloud says so.
        shorter = _fixture("wm-appliances")
        shorter[0]["properties"]["reported"]["timeToEnd"] = 1200
        shorter[0]["properties"]["reported"]["applianceState"] = "RUNNING"
        shorter[0]["properties"]["reported"]["userSelections"]["programUID"] = (
            "QUICK_20_MIN_PR_20MIN3KG"
        )
        api.appliances.return_value = shorter
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

        moved = hass.states.get("sensor.lave_linge_time_to_end_formatted")
        assert moved is not None
        assert moved.state == "00:20:00"

        # And it counts down from the new figure, not the old one.
        clock.monotonic.return_value = 1060.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
        after = hass.states.get("sensor.lave_linge_time_to_end_formatted")
        assert after is not None
        assert after.state == "00:19:30"


async def test_a_word_about_something_else_does_not_stand_the_clock_still(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Anything pushed brings every entity round, not only what it was about.

    Counting afresh from a figure that has not moved would put the clock back
    where it was every time a door opened.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)

        coordinator = entry.runtime_data.coordinator
        appliance_id = next(iter(coordinator.data))
        clock.monotonic.return_value = 1030.0
        coordinator._pushed(
            {
                "Payload": {
                    "Appliances": [
                        {
                            "ApplianceId": appliance_id,
                            "Metrics": [{"Name": "doorState", "Value": "CLOSED"}],
                        }
                    ]
                }
            }
        )
        await hass.async_block_till_done()

    # Half a minute has gone by, whatever the push was about.
    ticking = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert ticking is not None
    assert ticking.state == "00:09:30"


async def test_the_clock_takes_a_pushed_time_as_the_new_truth(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)

        coordinator = entry.runtime_data.coordinator
        appliance_id = next(iter(coordinator.data))
        clock.monotonic.return_value = 1300.0
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

    pushed = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert pushed is not None
    assert pushed.state == "00:15:00"


async def test_the_clock_stops_at_nothing_left(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 30
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 1045.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()

    finished = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert finished is not None
    assert finished.state == "00:00:00"


async def test_the_clock_gives_up_rather_than_counting_down_to_a_guess(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A wash still running with nothing left on the clock is a lie.

    The figure only counts down while it is fresh. Left long enough without a
    word from the appliance it would reach nothing left and say so as though
    it were a fact, so it says nothing instead.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 1800
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        # Long past when the next look should have brought a new figure.
        clock.monotonic.return_value = 9000.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()

    lost = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert lost is not None
    assert lost.state == "unknown"

    # The seconds the appliance last said are still there to be read.
    seconds = hass.states.get("sensor.lave_linge_time_to_end")
    assert seconds is not None
    assert seconds.state == "1800"


async def test_a_time_that_is_not_counting_down_stays_where_it_is(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A time the machine was set to does not move on its own."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["minFinishInTime"] = 14400
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 5000.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()

    steady = hass.states.get("sensor.lave_linge_shortest_finish_in_formatted")
    assert steady is not None
    assert steady.state == "04:00:00"


async def test_the_finish_is_fixed_to_a_moment(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Home Assistant counts down to a timestamp without being told to."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
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
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    first = hass.states.get("sensor.lave_linge_finishes_at")
    assert first is not None
    was = dt_util.parse_datetime(first.state)
    assert was is not None

    # A shorter programme is chosen and the cloud says so on the next look.
    shorter = _fixture("wm-appliances")
    shorter[0]["properties"]["reported"]["timeToEnd"] = 1200
    shorter[0]["properties"]["reported"]["applianceState"] = "RUNNING"
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
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
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
    # The programme the setting belongs to goes with it.
    assert command == {
        "userSelections": {
            "programUID": "COTTON_PR_ECO40-60",
            "analogTemperature": "60_CELSIUS",
        }
    }


async def test_a_field_of_its_own_is_sent_on_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Nothing to belong to, so nothing to say it belongs to."""
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.lave_linge_water_hardness", "option": "6"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"waterHardness": "STEP_6"}


async def test_a_flag_the_appliance_words_is_sent_in_its_words(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The panel lock is ON and OFF, and reports itself as true and false."""
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.lave_linge_panel_lock"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"uiLockMode": "ON"}

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.lave_linge_panel_lock"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"uiLockMode": "OFF"}


async def test_a_flag_with_no_words_is_sent_as_a_yes_or_a_no(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.lave_linge_stain"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command["userSelections"]["EWX1493A_stain"] is True


async def test_a_flag_reported_as_a_word_is_read_as_one(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Every word is true if it is only asked whether it is empty."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["uiLockMode"] = "OFF"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    lock = hass.states.get("switch.lave_linge_panel_lock")
    assert lock is not None
    assert lock.state == "off"
