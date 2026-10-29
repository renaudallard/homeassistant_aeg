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

import asyncio
import copy
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.aeg import async_remove_config_entry_device
from custom_components.aeg.capability import Capability
from custom_components.aeg.const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_BRAND,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_WS_URL,
    DOMAIN,
)
from custom_components.aeg.coordinator import capability_store
from custom_components.aeg.entity import pretty
from custom_components.aeg.errors import AegConnectionError, AegRefused
from custom_components.aeg.http import tag
from custom_components.aeg.names import is_setting

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
    mock.appliance_info.return_value = _fixture("wm-info")
    # How long the token has left is asked for, not awaited.
    mock.seconds_until_renewal = MagicMock(return_value=43200.0)
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


async def _again(hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock) -> None:
    """Set the entry up a second time, with the cloud still stood in for."""
    with _cloud(api):
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


async def test_a_tree_kept_by_another_version_is_asked_for_again(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    api: AsyncMock,
    hass_storage: dict[str, Any],
) -> None:
    """Reading one again costs a call, and reading it wrong costs the entry."""
    key = f"{DOMAIN}.{entry.entry_id}.capabilities"
    hass_storage[key] = {
        "version": 0,
        "minor_version": 1,
        "key": key,
        "data": {"an-appliance": {"hash": "a-hash", "tree": {}, "seen": []}},
    }

    await _setup(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    api.capabilities.assert_awaited_once()


def _two_appliances() -> list[dict[str, Any]]:
    """The washing machine, and a second one beside it."""
    listed = _fixture("wm-appliances")
    second = copy.deepcopy(listed[0])
    second["applianceId"] = "another-appliance"
    return [listed[0], second]


async def test_an_appliance_the_cloud_will_not_describe_is_left_out(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """One appliance turned down is no reason to take the account down."""
    api.appliances.return_value = _two_appliances()
    tree: dict[str, Any] = _fixture("wm-capabilities")

    async def described(appliance_id: str) -> dict[str, Any]:
        if appliance_id == "another-appliance":
            raise AegRefused("the capabilities were refused (404)")
        return tree

    api.capabilities.side_effect = described
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await _setup(hass, entry, api)
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("select.lave_linge_water_hardness") is not None
    # Left out is not newly added, so nothing loads the entry again for it.
    reload.assert_not_called()


async def test_an_appliance_described_before_goes_on_with_that(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A tree that has changed and cannot be read is still better than none.

    It is kept under the hash it was read under, so the next start asks again.
    """
    await _setup(hass, entry, api)
    changed = _fixture("wm-appliances")
    changed[0]["properties"]["reported"]["applianceInfo"]["capabilityHash"] = (
        "a-new-one"
    )
    api.appliances.return_value = changed
    api.capabilities.side_effect = AegConnectionError("unreachable")
    await _again(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("select.lave_linge_water_hardness") is not None

    api.capabilities.side_effect = None
    await _again(hass, entry, api)
    assert api.capabilities.await_count == 3


async def test_an_appliance_that_will_not_describe_itself_keeps_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """With nothing held for it, it is listed with nothing it can do.

    That read as an appliance with none of the fields it had entities for,
    and every one of them was taken out of the register, names, areas and
    automations along with it.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    before = er.async_entries_for_config_entry(registry, entry.entry_id)
    await capability_store(hass, entry).async_remove()
    api.capabilities.side_effect = AegRefused("the capabilities were refused (404)")
    await _again(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    after = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(after) == len(before)


async def test_an_appliance_never_described_waits_out_a_cloud_that_is_unwell(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Setting the entry up again later is what gets the answer."""
    api.capabilities.side_effect = AegConnectionError("unreachable")
    with _cloud(api):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_the_appliance_loads(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    # Capabilities describe the model, not its state, so they are read once.
    api.capabilities.assert_awaited_once()
    # And the account is listed once, not once to read what each appliance can
    # do and again for what it is doing a moment later.
    api.appliances.assert_awaited_once()


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


def _the_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    return devices[0]


async def test_the_device_is_named_for_the_model_on_the_box(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A listing calls every washing machine WM, which names none of them.

    The fixture is the field list the app decodes this answer into, with
    values of the kind an AEG washer gives, rather than a captured reply.
    """
    await _setup(hass, entry, api)
    device = _the_device(hass, entry)
    assert device.model == "LFR73164OE"
    # The number on the rating plate, which is what spares are looked up by.
    assert device.model_id == "914550402"


async def test_the_device_says_what_firmware_it_is_running(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The same version the update entity is about, not a second one."""
    await _setup(hass, entry, api)
    assert _the_device(hass, entry).sw_version == "v4.1.0S_argo"

    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.attributes["installed_version"] == "v4.1.0S_argo"


async def test_a_device_whose_appliance_is_quiet_about_it_says_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    quiet = _fixture("wm-appliances")
    del quiet[0]["properties"]["reported"]["networkInterface"]["swVersion"]
    api.appliances.return_value = quiet

    await _setup(hass, entry, api)
    assert _the_device(hass, entry).sw_version is None


async def test_an_appliance_that_will_not_say_keeps_the_type_it_listed_as(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """One answer short is not one appliance short."""
    api.appliance_info.side_effect = AegConnectionError("no such route")

    await _setup(hass, entry, api)
    assert entry.state is ConfigEntryState.LOADED
    device = _the_device(hass, entry)
    assert device.model == "WM"
    assert device.model_id is None


async def test_it_asks_what_an_appliance_is_once_and_keeps_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An appliance is one model for good, so the answer cannot go stale."""
    await _setup(hass, entry, api)
    assert api.appliance_info.await_count == 1

    await _again(hass, entry, api)
    assert api.appliance_info.await_count == 1


async def test_an_appliance_that_would_not_say_is_asked_again(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Nothing kept is nothing to keep, not a settled answer of nothing."""
    api.appliance_info.side_effect = AegConnectionError("not this time")
    await _setup(hass, entry, api)

    api.appliance_info.side_effect = None
    await _again(hass, entry, api)
    assert api.appliance_info.await_count == 2
    assert _the_device(hass, entry).model == "LFR73164OE"


async def test_the_washing_machine_comes_out_as_the_readme_says(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The README quotes these, and a quoted number goes stale on its own."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)

    assert len(entities) == 69
    assert len([e for e in entities if not e.disabled]) == 54

    # The control, not the record of the last one run kept out of sight.
    programme = hass.states.get("select.lave_linge_programme")
    assert programme is not None
    assert len(programme.attributes["options"]) == 34
    assert hass.states.get("select.lave_linge_programme_2") is None

    # Every appliance gets one, and it is a binary sensor rather than a sensor,
    # which is what somebody reads the README to find out.
    assert hass.states.get("binary_sensor.lave_linge_connection") is not None


async def test_nothing_offers_to_undo_the_appliance(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Not even hidden away with the maintenance counters.

    Disabled by default is protection against pressing one by accident, not
    against having it there to press.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)

    undoing = [
        e
        for e in entities
        if "networkInterface/command" in e.unique_id
        or "networkInterface/startUpCommand" in e.unique_id
    ]
    assert not undoing, undoing


async def test_one_left_over_from_an_older_version_is_taken_away(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An install that had them before this stopped making them."""
    registry = er.async_get(hass)
    listed = _fixture("wm-appliances")[0]["applianceId"]
    left_over = registry.async_get_or_create(
        Platform.BUTTON,
        DOMAIN,
        f"{listed}-networkInterface/startUpCommand-UNINSTALL",
        config_entry=entry,
    )

    await _setup(hass, entry, api)
    assert registry.async_get(left_over.entity_id) is None


async def test_a_number_it_reports_is_kept_as_history(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Home Assistant keeps none of it without being told what kind it is."""
    await _setup(hass, entry, api)

    counter = hass.states.get("sensor.lave_linge_cycles_run")
    assert counter is not None
    assert counter.attributes["state_class"] == "total_increasing"

    weight = hass.states.get("sensor.lave_linge_nominal_load")
    assert weight is not None
    assert weight.attributes["state_class"] == "measurement"
    # Nothing claims to know what an appliance weighs its load in.
    assert "unit_of_measurement" not in weight.attributes

    # A word is not a number, whatever the field holding it is typed as.
    phase = hass.states.get("sensor.lave_linge_cycle_phase")
    assert phase is not None
    assert "state_class" not in phase.attributes


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


async def test_a_finished_update_is_not_an_update_waiting(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The word an appliance uses when an update has gone through is UPDATE_OK.

    Two words that no appliance says were being read as the end of one, and
    that one was not, so a machine that had just updated said an update was
    waiting and gave the word itself as the version on offer.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["networkInterface"]["otaState"] = "UPDATE_OK"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.state == "off"
    assert (
        firmware.attributes["latest_version"]
        == firmware.attributes["installed_version"]
    )


async def test_a_word_nobody_can_read_is_not_an_update(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A later firmware can say something none of this knows.

    Reading that as an update in hand would offer the word itself as the
    version to move to, which is how a machine that had just updated came to
    say one was waiting.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["networkInterface"]["otaState"] = (
        "SOMETHING_NEW"
    )
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.state == "off"


async def test_an_update_waiting_on_somebody_says_so(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    state = listed[0]["properties"]["reported"]["networkInterface"]
    state["otaState"] = "READY_TO_UPDATE"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.state == "on"
    assert firmware.attributes["in_progress"] is False


async def test_an_update_running_says_it_is_running(
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


async def test_a_machine_keeping_its_update_state_somewhere_else_still_has_one(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The newer models keep a swUpdate group of their own.

    They write the same states in camel case, and had no firmware entity at
    all because only the network unit was looked at.
    """
    listed = _fixture("wm-appliances")
    reported = listed[0]["properties"]["reported"]
    del reported["networkInterface"]["otaState"]
    del reported["networkInterface"]["swVersion"]
    reported["swUpdate"] = {"swUpdateState": "updateAvailable"}
    reported["swVersions"] = {"niu": {"ver": "v9.9.9"}}
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    firmware = hass.states.get("update.lave_linge_firmware")
    assert firmware is not None
    assert firmware.state == "on"
    assert firmware.attributes["installed_version"] == "v9.9.9"


async def test_a_field_that_changed_platform_leaves_nothing_behind(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A field can move from one kind of entity to another between versions.

    Remote notifications was a select until the appliance was read as saying
    both of its values are set aside, which leaves nothing to choose between.
    The select was kept because the field is still there, and sat with the
    name and nothing to say.
    """
    registry = er.async_get(hass)
    appliance = _fixture("wm-appliances")[0]["applianceId"]
    was = registry.async_get_or_create(
        "select",
        DOMAIN,
        f"{appliance}-remoteNotificationPending",
        config_entry=entry,
        suggested_object_id="lave_linge_remote_notifications_old",
    )

    await _setup(hass, entry, api)

    assert registry.async_get(was.entity_id) is None
    now = hass.states.get("sensor.lave_linge_remote_notifications")
    assert now is not None and now.state == "OFF"


async def test_a_thermostat_an_appliance_never_had_is_taken_away(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine gathers up into no thermostat and never did.

    The three entities that stand for an appliance rather than a field were
    claimed whatever the appliance is, so one of them outlived any version
    that had made it.
    """
    registry = er.async_get(hass)
    appliance = _fixture("wm-appliances")[0]["applianceId"]
    stale = registry.async_get_or_create(
        "climate",
        DOMAIN,
        f"{appliance}-climate",
        config_entry=entry,
        suggested_object_id="lave_linge_thermostat",
    )

    await _setup(hass, entry, api)
    assert registry.async_get(stale.entity_id) is None


async def test_a_companion_entity_is_not_mistaken_for_a_stale_one(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Some entities add a word to the id of the field they come from.

    They go on the platform their field does, so comparing the kind must not
    take them for something left over.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    kept = {
        record.unique_id
        for record in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    appliance = _fixture("wm-appliances")[0]["applianceId"]
    assert f"{appliance}-timeToEnd-formatted" in kept
    assert f"{appliance}-timeToEnd-at" in kept
    assert f"{appliance}-executeCommand-START" in kept
    assert f"{appliance}-connection" in kept


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


async def test_settings_missing_at_the_start_come_back_when_they_are_said(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Keeping the register entry is no use without an entity behind it.

    Started while the machine said nothing of its wash settings, the controls
    for them sat restored and unavailable until the next start, whatever the
    machine said in between.
    """
    await _setup(hass, entry, api)

    partial = _fixture("wm-appliances")
    del partial[0]["properties"]["reported"]["userSelections"]
    api.appliances.return_value = partial
    await _again(hass, entry, api)
    quiet = hass.states.get("select.lave_linge_spin_speed")
    assert quiet is not None
    assert quiet.state == "unavailable"

    api.appliances.return_value = _fixture("wm-appliances")
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    back = hass.states.get("select.lave_linge_spin_speed")
    assert back is not None
    assert back.state != "unavailable"
    assert not back.attributes.get("restored")


async def test_a_failed_setup_does_not_leave_the_stream_open(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An entry that did not load has no business holding a connection open."""
    with (
        _cloud(api) as stream,
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


async def test_an_appliance_added_to_the_account_is_picked_up(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """What an appliance can do is read while the entry is being set up."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith("a-second-machine-")
    ]

    both = _fixture("wm-appliances")
    second = copy.deepcopy(both[0])
    second["applianceId"] = "a-second-machine"
    both.append(second)
    api.appliances.return_value = both
    with _cloud(api):
        freeze_time = dt_util.utcnow() + timedelta(minutes=1)
        async_fire_time_changed(hass, freeze_time)
        await hass.async_block_till_done()

    assert [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith("a-second-machine-")
    ]


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


async def test_an_appliance_a_listing_left_out_is_not_started_over(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Its entities outlive the listing, and have to outlive the one after.

    What each appliance has been seen reporting is what says a field is one
    the model does not have. Forgetting it for an appliance that was left out
    would take its entities away the next time it was listed while idle, which
    is the same mistake one step further along.
    """
    both = _fixture("wm-appliances")
    second = copy.deepcopy(both[0])
    second["applianceId"] = "a-second-machine"
    both.append(second)
    api.appliances.return_value = both
    await _setup(hass, entry, api)

    registry = er.async_get(hass)

    def standing() -> set[str]:
        return {
            e.entity_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id.startswith("a-second-machine-")
        }

    before = standing()
    assert before

    # Left out of one listing.
    api.appliances.return_value = _fixture("wm-appliances")
    await _again(hass, entry, api)

    # Then listed again, off and saying almost nothing, the way a machine sits
    # between washes.
    idle = copy.deepcopy(both)
    idle[1]["properties"]["reported"] = {
        "applianceState": "OFF",
        "applianceInfo": {"applianceType": "WM", "capabilityHash": "a-hash"},
    }
    api.appliances.return_value = idle
    await _again(hass, entry, api)

    assert standing() == before


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

    # The eco programme fixes the temperature at forty and says so, so the
    # control goes with it and only the one value is left on the list.
    temperature = hass.states.get(entities["userSelections/analogTemperature"])
    assert temperature is not None
    assert temperature.state == "unavailable"
    assert temperature.attributes["options"] == ["40_CELSIUS"]

    spin = hass.states.get(entities["userSelections/analogSpinSpeed"])
    assert spin is not None and spin.state == "1400_RPM"


async def test_a_reading_the_appliance_did_not_list_is_still_shown(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A capability tree is what the model says, not a promise it keeps."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["applianceState"] = "SOMETHING_NEW"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    state = hass.states.get("sensor.lave_linge_state")
    assert state is not None
    assert state.state == "SOMETHING_NEW"


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


def _push(entry: MockConfigEntry, *metrics: tuple[str, Any]) -> None:
    """What the cloud would push about the one appliance on the account."""
    coordinator = entry.runtime_data.coordinator
    coordinator._pushed(
        {
            "Payload": {
                "Appliances": [
                    {
                        "ApplianceId": next(iter(coordinator.data)),
                        "Metrics": [
                            {"Name": name, "Value": value} for name, value in metrics
                        ],
                    }
                ]
            }
        }
    )


async def test_the_clock_counts_from_when_the_wash_starts(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A programme says how long it takes from the moment it is picked.

    The figure does not move until the wash starts, so the time it stood
    waiting is not time taken off the wash.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "READY_TO_START"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 1600.0
        _push(entry, ("applianceState", "RUNNING"))
        await hass.async_block_till_done()

    started = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert started is not None
    assert started.state == "01:00:00"


async def test_the_clock_does_not_count_a_pause(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 1010.0
        _push(entry, ("applianceState", "PAUSED"), ("timeToEnd", 3590))
        await hass.async_block_till_done()
        # Ten minutes paused, then on again with the same time left.
        clock.monotonic.return_value = 1610.0
        _push(entry, ("applianceState", "RUNNING"))
        await hass.async_block_till_done()

    resumed = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert resumed is not None
    assert resumed.state == "00:59:50"


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


async def test_the_clock_waits_out_a_figure_that_moves_once_a_minute(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Looked at every half minute, a minute without a new figure is normal.

    The look that brings the next one lands a moment after the minute is up,
    and the clock should not go blank waiting for it.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    with patch("custom_components.aeg.sensor.time") as clock:
        clock.monotonic.return_value = 1000.0
        await _setup(hass, entry, api)
        clock.monotonic.return_value = 1030.4
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        clock.monotonic.return_value = 1060.5
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
        waiting = hass.states.get("sensor.lave_linge_time_to_end_formatted")
        assert waiting is not None
        assert waiting.state == "00:58:59"

        # Two looks and a minute without one is something not arriving.
        clock.monotonic.return_value = 1121.0
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
        await hass.async_block_till_done()

    lost = hass.states.get("sensor.lave_linge_time_to_end_formatted")
    assert lost is not None
    assert lost.state == "unknown"


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


async def test_the_finish_stays_put_between_new_figures(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    api: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A door, or a look that finds the same time left, is no reason to move it.

    Adding the same seconds to a later now would push the finish back by
    however long ago they were said.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["timeToEnd"] = 3600
    listed[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    api.appliances.return_value = listed

    await _setup(hass, entry, api)
    first = hass.states.get("sensor.lave_linge_finishes_at")
    assert first is not None

    freezer.tick(timedelta(seconds=50))
    _push(entry, ("doorState", "CLOSED"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=25))
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    later = hass.states.get("sensor.lave_linge_finishes_at")
    assert later is not None
    assert later.state == first.state


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


async def test_a_scale_that_names_some_steps_keeps_the_words_it_uses(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Water hardness is one scale of seven that names its first three steps.

    The cloud lists values alphabetically, so those three arrive as HARD,
    MEDIUM, SOFT and nothing says which of them is the first step. Numbering
    them off the order they came in would offer the hardest setting as one of
    seven, so they are shown as the appliance writes them.
    """
    await _setup(hass, entry, api)
    hardness = hass.states.get("select.lave_linge_water_hardness")
    assert hardness is not None
    assert hardness.attributes["options"] == [
        "HARD",
        "MEDIUM",
        "SOFT",
        "STEP_4",
        "STEP_5",
        "STEP_6",
        "STEP_7",
    ]
    assert hardness.state == "STEP_4"


async def test_a_level_is_sent_back_as_the_appliance_names_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.lave_linge_water_hardness", "option": "STEP_6"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"waterHardness": "STEP_6"}


async def test_a_refused_command_is_said_to_whoever_asked(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An appliance turning a setting down is not a fault in the integration.

    Home Assistant writes anything that is not one of its own errors out as
    an unexpected exception with a traceback, and the user gets nothing they
    can read.
    """
    await _setup(hass, entry, api)
    api.send_command.side_effect = AegConnectionError("the cloud refused it (406)")
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.lave_linge_water_hardness", "option": "STEP_6"},
            blocking=True,
        )
    assert raised.value.translation_key == "command_failed"
    assert raised.value.translation_placeholders == {
        "error": "the cloud refused it (406)"
    }
    # Turned down is not signed out.
    assert not list(entry.async_get_active_flows(hass, {"reauth"}))


async def test_a_group_inside_a_group_takes_its_own_programme(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """No appliance here nests them two deep, and the lookup has to hold if one does."""
    await _setup(hass, entry, api)
    coordinator = entry.runtime_data.coordinator
    appliance_id = next(iter(coordinator.data))
    reported = coordinator.data[appliance_id].reported
    reported["outer"] = {
        "programUID": "AN_OUTER_PROGRAMME",
        "inner": {"programUID": "AN_INNER_PROGRAMME", "rinse": "ON"},
    }

    await coordinator.send(appliance_id, "outer/inner/rinse", "OFF")
    _, command = api.send_command.await_args.args
    assert command == {
        "outer": {
            "programUID": "AN_OUTER_PROGRAMME",
            "inner": {"programUID": "AN_INNER_PROGRAMME", "rinse": "OFF"},
        }
    }


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
            "entity_id": entities["userSelections/analogSpinSpeed"],
            "option": "1200_RPM",
        },
        blocking=True,
    )
    api.send_command.assert_awaited_once()
    _, command = api.send_command.await_args.args
    # The programme the setting belongs to goes with it.
    assert command == {
        "userSelections": {
            "programUID": "COTTON_PR_ECO40-60",
            "analogSpinSpeed": "1200_RPM",
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
        {"entity_id": "select.lave_linge_water_hardness", "option": "STEP_6"},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"waterHardness": "STEP_6"}


async def test_a_whole_number_is_sent_whole(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Home Assistant hands every number over as a fraction.

    The appliance counts its seconds in whole ones and reports them that way,
    so 7200.0 is the same figure written a way it never writes it. 7200.0
    compares equal to 7200, so the type is what has to be looked at.
    """
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.lave_linge_finish_in", "value": 7200},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"stopTime": 7200}
    assert isinstance(command["stopTime"], int)


async def test_a_stop_time_that_is_not_set_reads_as_nothing(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The washer reports -1 until a stop time is set.

    It read -1 under a minimum of 0, a figure the control itself would not
    take back.
    """
    await _setup(hass, entry, api)
    finish = hass.states.get("number.lave_linge_finish_in")
    assert finish is not None
    assert finish.state == "unknown"

    _push(entry, ("stopTime", 7200))
    await hass.async_block_till_done()
    finish = hass.states.get("number.lave_linge_finish_in")
    assert finish is not None
    assert float(finish.state) == 7200


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


async def test_a_device_can_be_deleted_once_the_account_has_dropped_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Tidying up after an appliance has been unpaired in the vendor app."""
    await _setup(hass, entry, api)
    device = _the_device(hass, entry)

    # Still on the account, so deleting it would only lose its history until
    # the next look brought it back under a new device.
    assert not await async_remove_config_entry_device(hass, entry, device)

    api.appliances.return_value = []
    await entry.runtime_data.coordinator.async_refresh()
    assert await async_remove_config_entry_device(hass, entry, device)


async def test_a_device_is_kept_while_the_account_is_not_loaded(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Waiting to be signed in again, say, with nothing listed to go by.

    Asking used to fail with an unknown error and a traceback in the log.
    """
    await _setup(hass, entry, api)
    device = _the_device(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not await async_remove_config_entry_device(hass, entry, device)


async def test_the_manufacturer_is_what_the_appliance_says_it_is(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)
    assert _the_device(hass, entry).manufacturer == "AEG"


async def test_an_appliance_that_says_nothing_takes_the_account_brand(
    hass: HomeAssistant, hass_storage: dict[str, Any], api: AsyncMock
) -> None:
    """An Electrolux account with an appliance that will not say what it is."""
    elsewhere = MockConfigEntry(
        domain=DOMAIN,
        unique_id="someone@example.com",
        data={
            CONF_EMAIL: "someone@example.com",
            CONF_COUNTRY: "BE",
            CONF_BRAND: "electrolux",
            CONF_BASE_URL: "https://api.eu.ocp.electrolux.one",
            CONF_WS_URL: "wss://ws.eu.ocp.electrolux.one",
            CONF_ACCESS_TOKEN: "an-access-token",
            CONF_REFRESH_TOKEN: "a-refresh-token",
            CONF_EXPIRES_AT: 4102444800.0,
        },
    )
    elsewhere.add_to_hass(hass)
    api.appliance_info.return_value = {}

    await _setup(hass, elsewhere, api)
    assert _the_device(hass, elsewhere).manufacturer == "Electrolux"


async def test_a_setting_goes_under_configuration_and_a_control_does_not(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """Water hardness is plumbing; spin speed is this wash."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    # By the field rather than the entity id: two groups carry a programme,
    # and which of them a bare name lands on is not the point being made.
    by_field = {
        e.unique_id.split("-", 1)[1]: e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    for settled in (
        "waterHardness",
        "waterSoftenerMode",
        "endOfCycleSound",
        "uiLockMode",
        "defaultExtraRinse",
    ):
        assert by_field[settled].entity_category == EntityCategory.CONFIG, settled

    for used in (
        "userSelections/analogSpinSpeed",
        "userSelections/analogTemperature",
        "userSelections/programUID",
        "userSelections/steamValue",
    ):
        assert by_field[used].entity_category is None, used


async def test_a_setting_only_counts_where_it_can_be_set(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The same name read only is a reading like any other."""
    capability = Capability(path="waterHardness", access="read", kind="string")
    assert is_setting(capability.name)
    assert not (capability.writable and is_setting(capability.name))


async def test_the_picture_moves_with_the_reading(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The whole point of drawing a door by its state, end to end."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["doorState"] = "CLOSED"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    shut = hass.states.get("sensor.lave_linge_door")
    assert shut is not None
    assert shut.attributes["icon"] == "mdi:door-closed"

    coordinator = entry.runtime_data.coordinator
    appliance_id = next(iter(coordinator.data))
    coordinator._pushed(
        {
            "Payload": {
                "Appliances": [
                    {
                        "ApplianceId": appliance_id,
                        "Metrics": [{"Name": "doorState", "Value": "OPEN"}],
                    }
                ]
            }
        }
    )
    await hass.async_block_till_done()

    opened = hass.states.get("sensor.lave_linge_door")
    assert opened is not None
    assert opened.attributes["icon"] == "mdi:door-open"


async def test_a_reading_nobody_drew_keeps_the_guess_from_its_name(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    await _setup(hass, entry, api)

    hardness = hass.states.get("select.lave_linge_water_hardness")
    assert hardness is not None
    assert hardness.attributes["icon"] == "mdi:water-percent"

    state = hass.states.get("sensor.lave_linge_state")
    assert state is not None
    assert state.attributes["icon"] == "mdi:sleep", "the fixture is IDLE"


async def test_the_remote_control_agrees_with_the_buttons_beside_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The fixture sits in the state the appliance refuses commands in.

    The picture said the remote was working while every command button beside
    it was greyed out, which is the one combination that cannot both be right.
    """
    await _setup(hass, entry, api)

    remote = hass.states.get("sensor.lave_linge_remote_control")
    assert remote is not None
    assert remote.state == "NOT_SAFETY_RELEVANT_ENABLED"
    assert remote.attributes["icon"] == "mdi:remote-off"

    start = hass.states.get("button.lave_linge_execute_command_start")
    assert start is not None
    assert start.state == "unavailable", "the appliance is refusing commands"


async def test_a_reading_the_table_does_not_list_falls_back_where_it_should(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A field that is drawn by its reading, saying something nobody listed."""
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["applianceState"] = "SOMETHING_NEW"
    del listed[0]["properties"]["reported"]["doorState"]
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    invented = hass.states.get("sensor.lave_linge_state")
    assert invented is not None
    assert invented.attributes["icon"] == "mdi:information-outline"

    # And one the appliance has gone quiet about altogether.
    quiet = hass.states.get("sensor.lave_linge_door")
    assert quiet is None, "a field never reported gets no entity at all"


async def test_a_worded_flag_is_drawn_by_the_state_it_shows(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The appliance's word and Home Assistant's own state can disagree.

    A panel lock reporting DISABLED reads as off, and a picture chosen from
    the word rather than the state would show it shut.
    """
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["uiLockMode"] = "DISABLED"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    lock = hass.states.get("switch.lave_linge_panel_lock")
    assert lock is not None
    assert lock.state == "off"
    assert lock.attributes["icon"] == "mdi:lock-open-variant"


async def test_a_numbered_command_is_sent_as_a_number(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The app clears a personalised cycle by sending 0, not "0"."""
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    clear = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.endswith("-clearCyclePersonalizationCmd-0")
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": clear}, blocking=True
    )
    _, command = api.send_command.await_args.args
    assert command == {"clearCyclePersonalizationCmd": 0}


async def test_a_push_during_a_look_is_not_undone_by_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A command asks for a look at once, and its push tends to land mid way.

    The listing was asked for before the push and put back what it changed,
    which nothing then corrected for ten minutes while the stream ran.
    """
    await _setup(hass, entry, api)
    coordinator = entry.runtime_data.coordinator
    asked = asyncio.Event()
    answer = asyncio.Event()

    async def slow_listing() -> list[dict[str, Any]]:
        asked.set()
        await answer.wait()
        listing: list[dict[str, Any]] = _fixture("wm-appliances")
        return listing

    api.appliances.side_effect = slow_listing
    look = hass.async_create_task(coordinator.async_refresh())
    await asked.wait()
    _push(entry, ("doorState", "CLOSED"))
    answer.set()
    await look
    appliance = next(iter(coordinator.data.values()))
    assert appliance.reported["doorState"] == "CLOSED"


async def test_a_field_first_reported_later_gets_its_entity(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """What is seen used to be gathered only while setting up.

    A washing machine quiet about a setting at every start never got an entity
    for it, however often it reported the setting in between.
    """
    quiet = _fixture("wm-appliances")
    del quiet[0]["properties"]["reported"]["userSelections"]["analogTemperature"]
    api.appliances.return_value = quiet
    await _setup(hass, entry, api)
    registry = er.async_get(hass)

    def temperature() -> list[str]:
        return [
            e.entity_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.unique_id.endswith("-userSelections/analogTemperature")
        ]

    assert not temperature()

    # Still quiet about it when it is loaded again, so what brings the entity
    # back is the setting having been kept, not reported a second time.
    with _cloud(api):
        _push(entry, ("userSelections", {"analogTemperature": "40_CELSIUS"}))
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert temperature()


async def test_a_look_under_way_at_unload_arranges_nothing_after_it(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A look is let finish while the entry goes, and reads what it reads.

    One that found a wash about to end booked another look nothing would
    ever cancel, against an entry that was no longer there.
    """
    await _setup(hass, entry, api)
    coordinator = entry.runtime_data.coordinator
    nearly: list[dict[str, Any]] = _fixture("wm-appliances")
    nearly[0]["properties"]["reported"]["applianceState"] = "RUNNING"
    nearly[0]["properties"]["reported"]["timeToEnd"] = 30
    asked = asyncio.Event()
    answer = asyncio.Event()

    async def slow_listing() -> list[dict[str, Any]]:
        asked.set()
        await answer.wait()
        return nearly

    api.appliances.side_effect = slow_listing
    look = entry.async_create_task(hass, coordinator.async_refresh(), "look")
    await asked.wait()
    unloading = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
    await asyncio.sleep(0)
    answer.set()
    await look
    assert await unloading
    assert not coordinator._endings


async def test_fields_first_reported_one_push_at_a_time_load_it_once(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """A washing machine can report its settings a frame at a time.

    Each new field loaded the entry again, and each of those was a new
    listing, a new stream and every entity blinking out.
    """
    quiet = _fixture("wm-appliances")
    settings = quiet[0]["properties"]["reported"]["userSelections"]
    for name in ("analogTemperature", "analogSpinSpeed", "steamValue"):
        del settings[name]
    api.appliances.return_value = quiet
    await _setup(hass, entry, api)

    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        _push(entry, ("userSelections", {"analogTemperature": "40_CELSIUS"}))
        _push(entry, ("userSelections", {"analogSpinSpeed": "1400_RPM"}))
        _push(entry, ("userSelections", {"steamValue": "STEAM_OFF"}))
        await hass.async_block_till_done()
    reload.assert_called_once()


async def test_a_figure_that_arrives_as_its_listed_word_reads_unknown(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    api: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The washer's tree lets the shortest finishing time be a word.

    A word on a sensor held to being a length of time was refused by Home
    Assistant, and so was every update after it.
    """
    await _setup(hass, entry, api)
    registry = er.async_get(hass)
    seconds = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.endswith("-minFinishInTime")
    )
    # In seconds it starts hidden, beside the clock that reads the same.
    registry.async_update_entity(seconds, disabled_by=None)
    await _again(hass, entry, api)
    _push(entry, ("minFinishInTime", "INVALID_OR_NOT_SET_TIME"))
    await hass.async_block_till_done()
    shortest = hass.states.get(seconds)
    assert shortest is not None
    assert shortest.state == "unknown"
    assert "non-numeric" not in caplog.text

    _push(entry, ("minFinishInTime", 3600))
    await hass.async_block_till_done()
    shortest = hass.states.get(seconds)
    assert shortest is not None
    assert shortest.state == "3600"


async def test_a_setting_with_nothing_to_set_it_with_is_still_added(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    api: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The robot vacuum takes a language and gives no list of them.

    That makes it a reading, and a reading put under Configuration is one
    Home Assistant refuses to add at all.
    """
    tree: dict[str, Any] = _fixture("wm-capabilities")
    tree["language"] = {"access": "readwrite", "type": "string"}
    api.capabilities.return_value = tree
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["language"] = "fr"
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    assert "Error adding entity" not in caplog.text
    registry = er.async_get(hass)
    language = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.endswith("-language")
    )
    assert language.entity_category is None
    state = hass.states.get(language.entity_id)
    assert state is not None
    assert state.state == "fr"


def test_an_acronym_run_into_the_next_word_reads_apart() -> None:
    """The washer's fabric care readings sit under fCMiscellaneousState.

    That came out as F CMiscellaneous state.
    """
    assert pretty("fCMiscellaneousState/waterUsage") == (
        "FC miscellaneous state water usage"
    )
    # What already read well still does.
    assert pretty("analogTemperature") == "Analog temperature"
    assert pretty("tvocPPB") == "Tvoc PPB"
    assert pretty("xFan") == "X fan"


async def test_a_number_read_from_a_range_of_its_own_gets_its_name(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The robot vacuum's volume became a number once its range was read.

    The names had not been told, so it went by its field name instead.
    """
    tree: dict[str, Any] = _fixture("wm-capabilities")
    tree["soundVolume"] = {
        "access": "readwrite",
        "type": "number",
        "range": {"min": 0, "max": 100, "step": 10},
    }
    api.capabilities.return_value = tree
    listed = _fixture("wm-appliances")
    listed[0]["properties"]["reported"]["soundVolume"] = 50
    api.appliances.return_value = listed
    await _setup(hass, entry, api)

    volume = hass.states.get("number.lave_linge_volume")
    assert volume is not None
    assert volume.attributes["friendly_name"] == "Lave-linge Volume"


async def test_an_appliance_on_the_newer_data_model_is_sent_a_list(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """The newer air conditioner, the purifier and the vacuum declare one.

    The app sends those their commands as a list under commands, and they
    were being sent on their own, the way the older appliances take them.
    """
    tree: dict[str, Any] = _fixture("wm-capabilities")
    tree["dataModelVersion"] = {
        "access": "constant",
        "type": "string",
        "value": "DAM-1.0.0",
    }
    api.capabilities.return_value = tree
    await _setup(hass, entry, api)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.lave_linge_finish_in", "value": 7200},
        blocking=True,
    )
    _, command = api.send_command.await_args.args
    assert command == {"commands": [{"stopTime": 7200}]}


async def test_no_time_left_is_not_a_length_of_time(
    hass: HomeAssistant, entry: MockConfigEntry, api: AsyncMock
) -> None:
    """An idle washer says -1 for the time left.

    The clock read unknown, and the seconds beside it read -1 and kept it.
    """
    await _setup(hass, entry, api)
    left = hass.states.get("sensor.lave_linge_time_to_end")
    assert left is not None
    assert left.state == "unknown"

    _push(entry, ("timeToEnd", 3600))
    await hass.async_block_till_done()
    left = hass.states.get("sensor.lave_linge_time_to_end")
    assert left is not None
    assert left.state == "3600"


async def test_the_log_names_no_appliance_by_its_id(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    api: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The id is the product number, the serial and the network address.

    Setting up wrote it out whole, a line for each appliance, in the very log
    that is asked for in a bug report.
    """
    # Shaped as a real one is; the fixture's own has been hidden already.
    appliance_id = "914505616_00:54600049-443E07743904"
    listed = _fixture("wm-appliances")
    listed[0]["applianceId"] = appliance_id
    api.appliances.return_value = listed
    api.appliance_info.side_effect = AegConnectionError("not today")
    caplog.set_level(logging.DEBUG, logger="custom_components.aeg")
    await _setup(hass, entry, api)
    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.aeg")
    )
    assert "describes" in ours
    assert appliance_id not in ours
    assert tag(appliance_id) in ours
