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

"""Flags an appliance lets you set."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import SWITCH, Capability
from .coordinator import AegCoordinator
from .entity import AegEntity, fields

# What an appliance calls off, when it words a flag rather than setting it.
OFF_WORDS = frozenset({"OFF", "FALSE", "DISABLED", "NO", "CLOSED", "0"})


def worded(values: tuple[str, ...]) -> tuple[str, str] | None:
    """The on and off of a flag an appliance words, if that is what it does."""
    if len(values) != 2:
        return None
    off = next((value for value in values if value.upper() in OFF_WORDS), None)
    if off is None:
        return None
    return next(value for value in values if value != off), off


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegSwitch(coordinator, appliance_id, capability)
        for appliance_id, capability in fields(coordinator, SWITCH)
    )


class AegSwitch(AegEntity, SwitchEntity):
    """A flag that can be set.

    Some flags are words rather than a yes and a no. A washing machine locks
    its panel with ON and OFF while reporting the state of it as true and
    false, so what it is sent is not always what it says back.
    """

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._words = worded(capability.values)

    @property
    def available(self) -> bool:
        # Nothing to set on an appliance that cannot be reached, and nothing
        # to set on a field it will not take right now.
        return super().available and self.reachable and self.override.writable

    @property
    def is_on(self) -> bool | None:
        value = self.reported
        if value is None:
            return None
        if isinstance(value, str):
            # Every word is true otherwise, off included.
            return value.upper() not in OFF_WORDS
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send(self._words[0] if self._words else True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send(self._words[1] if self._words else False)
