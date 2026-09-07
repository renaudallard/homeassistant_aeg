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

"""Readings from an appliance."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AegConfigEntry
from .capability import SENSOR, Capability, counts_down, is_duration
from .coordinator import AegCoordinator
from .entity import AegEntity, fields


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    readings: list[SensorEntity] = []
    for appliance_id, capability in fields(coordinator, SENSOR):
        readings.append(AegSensor(coordinator, appliance_id, capability))
        if is_duration(capability):
            # The seconds are what the appliance says; the clock is what
            # anyone actually wants to read.
            readings.append(AegDuration(coordinator, appliance_id, capability))
        if counts_down(capability):
            readings.append(AegFinishesAt(coordinator, appliance_id, capability))
    add(readings)


class AegSensor(AegEntity, SensorEntity):
    """A field that can be read but not set."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        # Kept rather than read back off the entity: an attribute Home
        # Assistant never assigned is not there to be read.
        self._enum_options: tuple[str, ...] = ()
        if is_duration(capability):
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        elif capability.kind == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif capability.values and capability.kind == "string":
            # The appliance lists what this field can say, so let the frontend
            # translate it rather than showing the raw word.
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(capability.values)
            self._enum_options = capability.values

    @property
    def native_value(self) -> Any:
        value = self.reported
        if isinstance(value, (dict, list)):
            # Nothing sensible to show for a structure, and a state has to fit
            # in 255 characters.
            return None
        return value

    @property
    def available(self) -> bool:
        if self._enum_options:
            # A reading outside its own list would be logged as an error on
            # every refresh, which is worse than saying nothing.
            return super().available and self.reported in self._enum_options
        return super().available


class AegDuration(AegEntity, SensorEntity):
    """The same length of time, written as a clock reads it."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._attr_unique_id = f"{appliance_id}-{capability.path}-formatted"
        self._attr_name = f"{self._attr_name} formatted"

    @property
    def native_value(self) -> str | None:
        seconds = self.reported
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            return None
        # A washing machine says -1 for a time it does not have, such as the
        # end of a cycle it is not running.
        if seconds < 0:
            return None
        whole = int(seconds)
        return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


class AegFinishesAt(AegEntity, SensorEntity):
    """When the time left runs out.

    A countdown written as a clock only moves when the cloud says something,
    which is now and then rather than every second. The moment it finishes does
    not move at all, and Home Assistant counts down to a timestamp on its own,
    so this is the one that reads live without writing a state a second.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._attr_unique_id = f"{appliance_id}-{capability.path}-at"
        # Named for what it is rather than for the field it comes from, since
        # an appliance has one thing it is counting down to.
        self._attr_name = "Finishes at"
        self._at: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._work_out_when()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._work_out_when()
        super()._handle_coordinator_update()

    def _work_out_when(self) -> None:
        """Fix the finish to a moment, from the seconds left as they arrive."""
        seconds = self.reported
        usable = isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        if not usable or seconds < 0:
            self._at = None
            return
        # To the second: the appliance counts in seconds, and a finish that
        # wandered by a fraction on every update would be written out again
        # each time for no reason.
        self._at = (dt_util.utcnow() + timedelta(seconds=int(seconds))).replace(
            microsecond=0
        )

    @property
    def native_value(self) -> datetime | None:
        return self._at
