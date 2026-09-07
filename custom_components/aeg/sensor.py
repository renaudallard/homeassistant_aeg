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

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import SENSOR, Capability
from .coordinator import AegCoordinator
from .entity import AegEntity, fields


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegSensor(coordinator, appliance_id, capability)
        for appliance_id, capability in fields(coordinator, SENSOR)
    )


class AegSensor(AegEntity, SensorEntity):
    """A field that can be read but not set."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        # Kept rather than read back off the entity: an attribute Home
        # Assistant never assigned is not there to be read.
        self._enum_options: tuple[str, ...] = ()
        if capability.kind == "temperature":
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
