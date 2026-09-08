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

# A value that is a name and a number, as in STEP_4, is a step in a scale.
LEVEL = re.compile(r"^[A-Z][A-Z_]*_(\d+)$")


def numbering(values: tuple[str, ...]) -> dict[str, str]:
    """Number a scale, if that is what these values are.

    A value that is a name and a number says where it sits, so a field whose
    values all say so is shown as the places they name.

    A field that names some of its steps and numbers the rest says nothing
    about where the named ones go. The cloud hands values over in alphabetical
    order, so a washing machine offering SOFT, MEDIUM and HARD before STEP_4
    lists them as HARD, MEDIUM, SOFT, and numbering off that order puts the
    softest setting at the top of the scale and sends HARD to anyone asking
    for the first step. Nothing in what the appliance says puts those three
    back in order, so they keep the words it uses for them.
    """
    steps = [LEVEL.match(value) for value in values]
    if len(steps) < 2 or not all(steps):
        return {}
    numbered = [int(step.group(1)) for step in steps if step is not None]
    if numbered != list(range(1, len(values) + 1)):
        # The numbers do not land on their own places, so they count
        # something else.
        return {}
    return {value: str(place) for place, value in enumerate(values, start=1)}


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
        shown = numbering(capability.values)
        self._values = {shown.get(value, value): value for value in capability.values}
        self._shown = shown

    @property
    def available(self) -> bool:
        # Nothing to set on an appliance that cannot be reached, and nothing
        # to set on a field it will not take right now.
        return super().available and self.reachable and self.override.writable

    @property
    def options(self) -> list[str]:
        """The values the appliance will take in the state it is in.

        What a field accepts moves with the rest of the machine: an air
        conditioner drops TURBO from its fan speeds in its automatic and fan
        only modes. Offering one it has said it will not take only earns a
        refused command.

        Whatever it is set to now stays on the list even when the triggers
        leave it off, since a reading nobody can see is no better than a
        choice nobody can make.
        """
        allowed = self.override.values
        if allowed is None:
            return list(self._values)
        current = self.current_option
        return [
            shown
            for shown, value in self._values.items()
            if value in allowed or shown == current
        ]

    @property
    def current_option(self) -> str | None:
        value = self.reported
        if value not in self.capability.values:
            return None
        return self._shown.get(str(value), str(value))

    async def async_select_option(self, option: str) -> None:
        await self.send(self._values.get(option, option))
