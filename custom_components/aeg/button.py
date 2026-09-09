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

"""Commands an appliance accepts.

A command field is write only and lists what it will take, so each of those
values becomes a button of its own.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import BUTTON, Capability
from .coordinator import AegCoordinator
from .entity import AegEntity, fields, pretty
from .icons import icon_for_command


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    add(
        AegButton(coordinator, appliance_id, capability, command)
        for appliance_id, capability in fields(coordinator, BUTTON)
        for command in capability.values
    )


class AegButton(AegEntity, ButtonEntity):
    """One value of one command field."""

    def __init__(
        self,
        coordinator: AegCoordinator,
        appliance_id: str,
        capability: Capability,
        command: str,
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._command = command
        self._attr_unique_id = f"{appliance_id}-{capability.path}-{command}"
        # One command of a field that is never reported back, so there is no
        # reading to draw it by.
        self._drawn = None
        self._attr_name = f"{self.plain_name} {pretty(command)}"
        self._attr_icon = icon_for_command(command)

    @property
    def available(self) -> bool:
        # A command field is never reported back, so there is no value to read.
        appliance = self.appliance
        return (
            self.coordinator.last_update_success
            and appliance is not None
            and appliance.connected
            # A washing machine takes START when it is ready to start, and not
            # while it is running.
            and self.override.allows(self._command)
        )

    async def async_press(self) -> None:
        await self.send(self._command)
