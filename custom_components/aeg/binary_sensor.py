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

"""Flags an appliance reports, and the problems it complains about."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import ALERTS, BINARY_SENSOR
from .coordinator import AegCoordinator
from .entity import AegApplianceEntity, AegEntity, fields


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    flags: list[BinarySensorEntity] = [
        AegAlerts(coordinator, appliance_id, capability)
        if capability.kind in ALERTS
        else AegBinarySensor(coordinator, appliance_id, capability)
        for appliance_id, capability in fields(coordinator, BINARY_SENSOR)
    ]
    # One that stays available whatever the appliance is doing, so an appliance
    # that has dropped off the network can say so.
    flags += [
        AegConnection(coordinator, appliance_id) for appliance_id in coordinator.data
    ]
    add(flags)


class AegBinarySensor(AegEntity, BinarySensorEntity):
    """A flag that can be read but not set."""

    @property
    def is_on(self) -> bool | None:
        value = self.reported
        return None if value is None else bool(value)


class AegAlerts(AegEntity, BinarySensorEntity):
    """Whatever the appliance is currently complaining about.

    The appliance reports a list of codes, empty when there is nothing wrong.
    One entity says whether anything is wrong, and carries the codes, which is
    more use than a sensor holding a list nobody can read.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def _active(self) -> list[str]:
        value = self.reported
        if not isinstance(value, list):
            return []
        return [
            # A code is usually a word. Anything else is shown as it came, so
            # a model that reports something richer is not thrown away.
            str(alert.get("code") or alert.get("name") or alert)
            if isinstance(alert, dict)
            else str(alert)
            for alert in value
        ]

    @property
    def is_on(self) -> bool | None:
        return None if self.reported is None else bool(self._active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"alerts": self._active}

    @property
    def available(self) -> bool:
        # An empty list is an answer: nothing is wrong.
        appliance = self.appliance
        return (
            self.coordinator.last_update_success
            and appliance is not None
            and appliance.connected
            and self.reported is not None
        )


class AegConnection(AegApplianceEntity, BinarySensorEntity):
    """Whether the cloud can still hear the appliance.

    Everything else goes unavailable when an appliance drops off the network,
    which is right but says nothing about why. This one stays put and answers
    that, so a machine that cannot reach the cloud looks like a machine that
    cannot reach the cloud rather than like a broken integration.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Connection"

    def __init__(self, coordinator: AegCoordinator, appliance_id: str) -> None:
        super().__init__(coordinator, appliance_id)
        self._attr_unique_id = f"{appliance_id}-connection"

    @property
    def is_on(self) -> bool:
        appliance = self.appliance
        return appliance is not None and appliance.connected

    @property
    def available(self) -> bool:
        # Only the account being unreachable can silence this one.
        return self.coordinator.last_update_success and self.appliance is not None
