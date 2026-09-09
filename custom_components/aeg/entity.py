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

from typing import Any

from homeassistant.const import EntityCategory, Platform, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .capability import (
    RUNNING,
    STATE,
    Capability,
    is_housekeeping,
    platform_for,
    value_at,
)
from .const import CONF_BRAND, DOMAIN, brand_for
from .coordinator import AegCoordinator, Appliance
from .icons import icon_for, icon_for_reading
from .names import CAMEL, MODEL_PREFIX, PLATFORMS_FOR, is_setting, key_for, readable
from .triggers import Override


def pretty(name: str) -> str:
    """Turn a field name into something worth reading.

    Words already in capitals are left alone, so an acronym stays an acronym
    while analogTemperature becomes what you would expect.
    """
    segments = [MODEL_PREFIX.sub("", part) for part in name.split("/")]
    words = " ".join(segments).replace("_", " ")
    parts = CAMEL.sub(r" \1", words).split()
    if not parts:
        return name
    readable = [parts[0].capitalize() if parts[0].islower() else parts[0]]
    readable += [
        word.lower() if word[:1].isupper() and word[1:].islower() else word
        for word in parts[1:]
    ]
    return " ".join(readable)


def degrees(capability: Capability) -> UnitOfTemperature:
    """Which scale a temperature is on.

    An appliance writes the scale into the field name and describes both where
    it has both, as ambientTemperatureC beside ambientTemperatureF. Reading one
    as the other is a reading wrong by fifty degrees, and wrong again once Home
    Assistant converts it for somebody who works in the other one.
    """
    if capability.name.endswith("F"):
        return UnitOfTemperature.FAHRENHEIT
    return UnitOfTemperature.CELSIUS


def as_set(value: float) -> float | int:
    """A number in the shape the appliance sends it in.

    Home Assistant hands every number over as a fraction, and an appliance
    that counts its degrees and its seconds in whole ones reports them whole.
    Sending 22.0 where it said 22 is the same reading written a way it never
    writes it, so a whole number goes back whole.
    """
    return int(value) if value.is_integer() else value


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


def lacks(coordinator: AegCoordinator, appliance: Appliance, field: Capability) -> bool:
    """Whether this model is known not to have a field its tree describes.

    A capability tree covers a range of models, so it lists fields a given
    machine does not have, and an entity for one of those is worth taking away.

    A field missing from what the appliance last said is a different thing. A
    machine that has dropped off the network, or one that has gone quiet about
    a whole group of settings, is not saying it lacks anything, and reading it
    that way took the entities off an appliance that was merely asleep. So the
    only fields given up on are the ones it has never once reported, and
    nothing is given up on while it is out of reach.
    """
    if not field.readable:
        # A command is never reported back, so there is nothing to look for.
        return False
    if not appliance.connected or not appliance.reported:
        return False
    return field.path not in coordinator.seen(appliance.id)


def provided(coordinator: AegCoordinator) -> dict[str, str]:
    """Every field this account has entities for, and what each one becomes.

    An entity's unique id is the appliance and the field. Some entities add a
    word of their own to that: a button for each command a field takes, a clock
    beside a length of time, a finishing time beside a countdown. Answering
    with what they all start with keeps those without this having to know every
    kind of entity there is, which it got wrong once already. Each of those
    goes on the platform its field does, so the kind travels with the id.
    """
    # Whether an appliance gathers up into a thermostat is the one thing here
    # that has to be asked of the platform that makes them, and that platform
    # is reached through this package, so it cannot be imported at the top.
    from .climate import gathers

    ids: dict[str, str] = {}
    for appliance_id, appliance in coordinator.data.items():
        # Whether the appliance is reachable at all is not a field of it.
        ids[f"{appliance_id}-connection"] = Platform.BINARY_SENSOR
        # It keeps its firmware entity through going quiet about the update,
        # the same way a field does, since silence is not the absence of one.
        ids[f"{appliance_id}-firmware"] = Platform.UPDATE
        fields = {capability.path: capability for capability in appliance.capabilities}
        if gathers(fields):
            ids[f"{appliance_id}-climate"] = Platform.CLIMATE
        for capability in appliance.capabilities:
            platform = platform_for(capability)
            if platform is None or lacks(coordinator, appliance, capability):
                continue
            ids[f"{appliance_id}-{capability.path}"] = platform
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

    def at(self, path: str) -> Any:
        """What the appliance last said about one of its fields."""
        appliance = self.appliance
        return None if appliance is None else value_at(appliance.reported, path)

    def override_for(self, path: str) -> Override:
        """What the appliance says about one field in the state it is in."""
        appliance = self.appliance
        if appliance is None:
            return Override()
        return appliance.overrides.get(path, Override())

    @property
    def running(self) -> bool:
        """Whether the appliance says it is doing something."""
        return str(self.at(STATE)).upper() == RUNNING

    @property
    def reachable(self) -> bool:
        """Whether the cloud can still hear the appliance."""
        appliance = self.appliance
        return appliance is not None and appliance.connected

    @property
    def device_info(self) -> DeviceInfo:
        appliance = self.appliance
        # What the appliance says it is, and failing that the brand the
        # account signs in as, which is the only other thing there is to say.
        entry = self.coordinator.config_entry
        account = brand_for(entry.data.get(CONF_BRAND) if entry else None).name
        return DeviceInfo(
            identifiers={(DOMAIN, self._appliance_id)},
            manufacturer=(appliance.made_by if appliance else None) or account,
            name=appliance.name if appliance else "AEG appliance",
            model=appliance.sold_as if appliance else None,
            model_id=appliance.product_number if appliance else None,
            # The network unit's, which is the one an update is about and so
            # the one the update entity shows. Two firmware versions on a
            # device page that disagreed would be worse than one.
            sw_version=appliance.firmware if appliance else None,
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
        # What to call it if Home Assistant has not been given anything
        # better, and what anything built on this entity calls itself.
        self.plain_name = readable(capability.name) or pretty(capability.path)
        key = key_for(capability.name)
        platform = platform_for(capability)
        if platform and platform in PLATFORMS_FOR.get(key, frozenset()):
            # Named where it can be translated, since a name set here would
            # win over the translation and there would be no point to it.
            self._attr_translation_key = key
        else:
            # The whole path, because two groups can hold the same field and
            # one name for both is no name at all.
            self._attr_name = pretty(capability.path)
        # What to draw when the reading itself has nothing to say, which is
        # most fields and every reading nobody listed.
        self._attr_icon = icon_for(capability)
        self._drawn_as = (platform, key)
        if is_housekeeping(capability):
            # Worth having, not worth showing next to the wash.
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        elif capability.writable and is_setting(capability.name):
            # Something about the machine rather than about the wash, so it
            # goes under Configuration and stays out of the way. Only where it
            # can be set: the same name read only is a reading like any other.
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """What the appliance last said is worth reading after it stops saying it.

        A washing machine turns itself off at the end of a cycle and drops off
        the network, and the cloud goes on reporting what it last said. Hiding
        all of that at the moment someone goes to look at how the wash went is
        no help, and the connection sensor is there to say the machine has gone
        rather than every other entity saying it at once.

        A field the appliance stops reporting is another matter: that is how a
        model says it does not have something its capabilities describe.
        """
        return (
            super().available
            and self.appliance is not None
            and self.reported is not None
        )

    @property
    def icon(self) -> str | None:
        """A picture for this field, moving with the reading where that helps.

        Home Assistant asks for this again on every state it writes, so a door
        can look open when it is open. Overriding the property is what makes
        that possible: an icon assigned once is assigned for good, and the
        declared form Home Assistant reads from a file cannot be used here
        because it will only take a reading written in lower case, which these
        appliances do not oblige with.
        """
        platform, key = self._drawn_as
        return icon_for_reading(platform, key, self.reported) or self._attr_icon

    @property
    def override(self) -> Override:
        """What the appliance says about this field in the state it is in."""
        return self.override_for(self.capability.path)

    @property
    def reported(self) -> Any:
        return self.at(self.capability.path)

    async def send(self, value: Any) -> None:
        await self.coordinator.send(self._appliance_id, self.capability.path, value)
