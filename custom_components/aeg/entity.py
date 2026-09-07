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

"""What every AEG entity has in common.

An entity stands for one field of one appliance. Which field it is comes from
the capability tree, so the platforms are thin: they say how a value is
presented and, where it can be set, how it is sent back.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .capability import Capability, is_housekeeping, platform_for, value_at
from .const import DOMAIN
from .coordinator import AegCoordinator, Appliance
from .triggers import Override

# A model code stuck on the front of a field name, as in EWX1493A_easyIron.
MODEL_PREFIX = re.compile(r"^[A-Z]{2,}[0-9A-Z]*_")


def pretty(name: str) -> str:
    """Turn a field name into something worth reading.

    Words already in capitals are left alone, so an acronym stays an acronym
    while analogTemperature becomes what you would expect.
    """
    segments = [MODEL_PREFIX.sub("", part) for part in name.split("/")]
    words = " ".join(segments).replace("_", " ")
    parts = re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", words).split()
    if not parts:
        return name
    readable = [parts[0].capitalize() if parts[0].islower() else parts[0]]
    readable += [
        word.lower() if word[:1].isupper() and word[1:].islower() else word
        for word in parts[1:]
    ]
    return " ".join(readable)


def carried(appliance: Appliance, capability: Capability) -> bool:
    """Whether this appliance actually has the field it describes.

    A capability tree covers a range of models, so it lists fields a given
    machine does not have. Those are never reported, and an entity for one
    would sit there unavailable for good.
    """
    if not capability.readable:
        # A command is never reported back, so there is nothing to look for.
        return True
    return value_at(appliance.reported, capability.path) is not None


def fields(coordinator: AegCoordinator, platform: str) -> list[tuple[str, Capability]]:
    """Every field on the account that belongs to one platform."""
    return [
        (appliance_id, capability)
        for appliance_id, appliance in coordinator.data.items()
        for capability in appliance.capabilities
        if platform_for(capability) == platform and carried(appliance, capability)
    ]


def provided(coordinator: AegCoordinator) -> set[str]:
    """Every field this account has entities for, by the id they start with.

    An entity's unique id is the appliance and the field. Some entities add a
    word of their own to that: a button for each command a field takes, a clock
    beside a length of time, a finishing time beside a countdown. Answering
    with what they all start with keeps those without this having to know every
    kind of entity there is, which it got wrong once already.
    """
    ids: set[str] = set()
    for appliance_id, appliance in coordinator.data.items():
        # Whether the appliance is reachable at all is not a field of it.
        ids.add(f"{appliance_id}-connection")
        for capability in appliance.capabilities:
            if platform_for(capability) is None or not carried(appliance, capability):
                continue
            ids.add(f"{appliance_id}-{capability.path}")
    return ids


class AegApplianceEntity(CoordinatorEntity[AegCoordinator]):
    """Something about one appliance, whether or not it is a field of it."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AegCoordinator, appliance_id: str) -> None:
        super().__init__(coordinator)
        self._appliance_id = appliance_id

    @property
    def appliance(self) -> Appliance | None:
        return self.coordinator.data.get(self._appliance_id)

    @property
    def device_info(self) -> DeviceInfo:
        appliance = self.appliance
        return DeviceInfo(
            identifiers={(DOMAIN, self._appliance_id)},
            manufacturer="AEG",
            name=appliance.name if appliance else "AEG appliance",
            model=appliance.model if appliance else None,
        )


class AegEntity(AegApplianceEntity):
    """One field of one appliance."""

    def __init__(
        self,
        coordinator: AegCoordinator,
        appliance_id: str,
        capability: Capability,
    ) -> None:
        super().__init__(coordinator, appliance_id)
        self.capability = capability
        self._attr_unique_id = f"{appliance_id}-{capability.path}"
        # The whole path, because two groups can hold the same field and one
        # name for both is no name at all.
        self._attr_name = pretty(capability.path)
        if is_housekeeping(capability):
            # Worth having, not worth showing next to the wash.
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        """Unavailable when the account is unreachable or the machine is off.

        A field the appliance stops reporting is unavailable too, which is how
        a model says it does not have something its capabilities describe.
        """
        appliance = self.appliance
        return (
            super().available
            and appliance is not None
            and appliance.connected
            and self.reported is not None
        )

    @property
    def override(self) -> Override:
        """What the appliance says about this field in the state it is in."""
        appliance = self.appliance
        if appliance is None:
            return Override()
        return appliance.overrides.get(self.capability.path, Override())

    @property
    def reported(self) -> Any:
        appliance = self.appliance
        if appliance is None:
            return None
        return value_at(appliance.reported, self.capability.path)

    async def send(self, value: Any) -> None:
        await self.coordinator.send(self._appliance_id, self.capability.path, value)
