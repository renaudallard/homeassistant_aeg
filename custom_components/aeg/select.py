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

"""Choices an appliance offers."""

from __future__ import annotations

import re

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import SELECT, Capability
from .coordinator import AegCoordinator
from .entity import AegEntity, fields

# A value that is a name and a number, as in STEP_4, is a numbered level. The
# number is the whole of what it says, so that is what is shown.
LEVEL = re.compile(r"^[A-Z][A-Z_]*_(\d+)$")


def shown_as(value: str) -> str:
    found = LEVEL.match(value)
    return found.group(1) if found else value


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegSelect(coordinator, appliance_id, capability)
        for appliance_id, capability in fields(coordinator, SELECT)
    )


class AegSelect(AegEntity, SelectEntity):
    """A field with a fixed set of values that can be set."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        # What the appliance calls each value, by what it is shown as.
        self._values = {shown_as(value): value for value in capability.values}
        self._attr_options = list(self._values)

    @property
    def available(self) -> bool:
        # A field the appliance will not take right now is not offered.
        return super().available and self.override.writable

    @property
    def current_option(self) -> str | None:
        value = self.reported
        if value not in self.capability.values:
            return None
        return shown_as(str(value))

    async def async_select_option(self, option: str) -> None:
        await self.send(self._values.get(option, option))
