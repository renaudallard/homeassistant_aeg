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

"""Firmware an appliance is running, and whatever it is being offered.

An appliance says what it is running and what its network unit is doing about
an update, which is enough to say whether one is in hand. It does not say what
version is on offer, so what it does say about the update stands in for that.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import value_at
from .coordinator import AegCoordinator
from .entity import AegApplianceEntity

# Where the network unit keeps what it is running and what it is doing.
STATE = "networkInterface/otaState"
VERSION = "networkInterface/swVersion"
OFFERED = "networkInterface/niuSwUpdateCurrentDescription"

# Nothing in hand: whatever it is running is whatever there is.
SETTLED = frozenset({"IDLE", "UPDATE_COMPLETE", "UPDATE_COMPLETED", "UPDATE_ABORT"})

# Something in hand and moving on its own.
WORKING = frozenset(
    {
        "DESCRIPTION_DOWNLOADING",
        "FW_DOWNLOAD_START",
        "FW_DOWNLOADING",
        "FW_SIGNATURE_CHECK",
        "FW_UPDATE_IN_PROGRESS",
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegFirmware(coordinator, appliance_id)
        for appliance_id, appliance in coordinator.data.items()
        # Only an appliance that says what its network unit is doing.
        if value_at(appliance.reported, STATE) is not None
    )


class AegFirmware(AegApplianceEntity, UpdateEntity):
    """What the appliance is running, and whether it is being given more."""

    _attr_device_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Firmware"
    # Progress, but not install: the appliance updates itself and says how far
    # it has got, and Home Assistant only reads that when it is told to.
    _attr_supported_features = UpdateEntityFeature.PROGRESS

    def __init__(self, coordinator: AegCoordinator, appliance_id: str) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}-firmware"

    def _at(self, path: str) -> Any:
        appliance = self.appliance
        return None if appliance is None else value_at(appliance.reported, path)

    @property
    def installed_version(self) -> str | None:
        version = self._at(VERSION)
        return None if version is None else str(version)

    @property
    def latest_version(self) -> str | None:
        """What is on offer, as far as the appliance will say.

        It does not publish a version to come, so what it says about the update
        stands in for one, and its own word for what it is doing stands in for
        that. Anything settled means what is running is all there is.
        """
        state = self._at(STATE)
        if state is None or str(state).upper() in SETTLED:
            return self.installed_version
        offered = self._at(OFFERED)
        return str(offered) if offered else str(state)

    @property
    def in_progress(self) -> bool:
        state = self._at(STATE)
        return state is not None and str(state).upper() in WORKING
