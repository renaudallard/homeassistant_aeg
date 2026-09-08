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

"""Numbers an appliance lets you set."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import NUMBER, Capability
from .coordinator import AegCoordinator
from .entity import AegEntity, as_set, degrees, fields


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegNumber(coordinator, appliance_id, capability)
        for appliance_id, capability in fields(coordinator, NUMBER)
    )


class AegNumber(AegEntity, NumberEntity):
    """A field that takes a value within a range the appliance gave us."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        if capability.kind == "temperature":
            self._attr_native_unit_of_measurement = degrees(capability)

    @property
    def available(self) -> bool:
        # Nothing to set on an appliance that cannot be reached, and nothing
        # to set on a field it will not take right now.
        return super().available and self.reachable and self.override.writable

    @property
    def native_min_value(self) -> float:
        """The lowest it will take, which moves with the rest of the machine.

        An oven takes a temperature anywhere from 30 to 230 in general and
        between 110 and 130 on one of its programmes. What a capability
        describes is what the model can do; what the appliance says it will
        take right now is what to offer.
        """
        if self.override.minimum is not None:
            return self.override.minimum
        if self.capability.minimum is not None:
            return self.capability.minimum
        return super().native_min_value

    @property
    def native_max_value(self) -> float:
        if self.override.maximum is not None:
            return self.override.maximum
        if self.capability.maximum is not None:
            return self.capability.maximum
        return super().native_max_value

    @property
    def native_step(self) -> float | None:
        return self.override.step or self.capability.step or super().native_step

    @property
    def native_value(self) -> float | None:
        value = self.reported
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.send(as_set(value))
