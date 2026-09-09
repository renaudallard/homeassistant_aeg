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

"""Tests for what gets handed over when something is wrong.

People paste this into bug reports, so what is not in it matters as much as
what is.
"""

import json
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aeg.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from tests.test_entities import _setup, api, entry  # noqa: F401


async def test_it_says_what_the_appliance_can_do(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    """A report about a model nobody has is worth nothing without this."""
    await _setup(hass, entry, api)
    report = await async_get_config_entry_diagnostics(hass, entry)

    appliances = report["appliances"]
    assert len(appliances) == 1
    machine = appliances[0]
    assert machine["model"] == "WM"
    assert machine["connected"] is True
    assert len(machine["describes"]) > 100

    door = next(f for f in machine["describes"] if f["path"] == "doorState")
    assert door["access"] == "read"
    assert door["becomes"] == "sensor"

    # What it will take right now, which is the other half of a bug report
    # about a button that will not press.
    assert "executeCommand" in machine["accepts_now"]

    # And of one about a number that will not go where somebody wants it. The
    # range a field describes is not the one being offered.
    temperature = machine["accepts_now"]["userSelections/analogTemperature"]
    assert set(temperature) == {"access", "values", "disabled", "min", "max", "step"}


async def test_it_says_whether_the_stream_is_carrying_it(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    await _setup(hass, entry, api)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["polling"]["last_look_worked"] is True
    assert report["polling"]["every"]


async def test_it_gives_nothing_away(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    await _setup(hass, entry, api)
    report = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(report)

    for secret in (
        "someone@example.com",
        "an-access-token",
        "a-refresh-token",
    ):
        assert secret not in text

    # The account is still recognisable as an account, just not as anyone's.
    assert report["entry"]["country"] == "BE"
    assert "hidden" in report["entry"]["email"]


async def test_a_device_hands_over_only_its_own_appliance(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    """A report is about one machine, and a household makes the account four
    times the size for no gain."""
    await _setup(hass, entry, api)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1

    report = await async_get_device_diagnostics(hass, entry, devices[0])
    assert len(report["appliances"]) == 1
    machine = report["appliances"][0]
    assert machine["model"] == "WM"
    assert len(machine["describes"]) > 100
    # The same shape as the account's, so one report reads like the other.
    account = await async_get_config_entry_diagnostics(hass, entry)
    assert set(report) == set(account)
    assert machine == account["appliances"][0]


async def test_a_device_the_account_has_dropped_hands_over_nothing(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    """Better an empty report than a download that fails."""
    await _setup(hass, entry, api)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)

    api.appliances.return_value = []
    await entry.runtime_data.coordinator.async_refresh()

    report = await async_get_device_diagnostics(hass, entry, devices[0])
    assert report["appliances"] == []


async def test_the_device_report_gives_nothing_away_either(
    hass: HomeAssistant,
    entry: MockConfigEntry,  # noqa: F811
    api: AsyncMock,  # noqa: F811
) -> None:
    await _setup(hass, entry, api)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    text = json.dumps(await async_get_device_diagnostics(hass, entry, devices[0]))

    for secret in ("an-access-token", "a-refresh-token", "someone@example.com"):
        assert secret not in text
