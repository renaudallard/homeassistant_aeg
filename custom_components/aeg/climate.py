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

"""An air conditioner, as a thermostat rather than as a pile of settings.

Everything here is also available as the selects and numbers the generic
mapping makes of it. This gathers the five of them that belong together into
the one control Home Assistant already has for the job.

An appliance qualifies by describing a mode it can be set to and a target
temperature, which is what an air conditioner does and a washing machine does
not.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AegConfigEntry
from .capability import STATE, Capability
from .coordinator import AegCoordinator
from .entity import AegApplianceEntity, as_set

_LOGGER = logging.getLogger(__name__)

MODE = "mode"
TARGET = "targetTemperatureC"
AMBIENT = "ambientTemperatureC"
FAN = "fanSpeedSetting"
SWING = "verticalSwing"
COMMAND = "executeCommand"

# What an appliance calls each way of running, against what Home Assistant
# calls it. Anything it offers that is not here is left out rather than
# guessed at.
MODES: dict[str, HVACMode] = {
    "AUTO": HVACMode.AUTO,
    "COOL": HVACMode.COOL,
    "HEAT": HVACMode.HEAT,
    "DRY": HVACMode.DRY,
    "FANONLY": HVACMode.FAN_ONLY,
    "OFF": HVACMode.OFF,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    thermostats = []
    for appliance_id, appliance in coordinator.data.items():
        fields = {capability.path: capability for capability in appliance.capabilities}
        if gathers(fields):
            thermostats.append(AegClimate(coordinator, appliance_id, fields))
    add(thermostats)


def gathers(fields: dict[str, Capability]) -> bool:
    """Whether an appliance's fields gather up into a thermostat.

    A mode it can be set to and a target temperature it will take, which is
    what an air conditioner has and a washing machine has not. Asked from
    outside as well, so that an appliance which has never had a thermostat is
    not held to have one.
    """
    mode = fields.get(MODE)
    target = fields.get(TARGET)
    return bool(mode and mode.values and target and target.writable)


class AegClimate(AegApplianceEntity, ClimateEntity):
    """An appliance that heats or cools a room."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: AegCoordinator,
        appliance_id: str,
        fields: dict[str, Capability],
    ) -> None:
        super().__init__(coordinator, appliance_id)
        self._fields = fields
        self._attr_unique_id = f"{appliance_id}-climate"

        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if self._turns("OFF") is not None:
            features |= ClimateEntityFeature.TURN_OFF
        if self._turns("ON") is not None:
            features |= ClimateEntityFeature.TURN_ON
        fan = fields.get(FAN)
        if fan and fan.values:
            features |= ClimateEntityFeature.FAN_MODE
        swing = fields.get(SWING)
        if swing and swing.values:
            features |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = features

    def _offered(self, path: str) -> list[str] | None:
        """What one of the gathered fields will take in the state it is in.

        An appliance says what a field accepts right now as well as what it
        accepts in general: an air conditioner drops TURBO from its fan speeds
        in its automatic and fan only modes, and will not take a fan speed at
        all while it is drying. Offering one it has said it will not take only
        earns a refused command.

        Whatever it is set to now stays on the list, since a reading nobody
        can see is no better than a choice nobody can make.
        """
        field = self._fields.get(path)
        if field is None or not field.values:
            return None
        current = self.at(path)
        override = self.override_for(path)
        if not override.writable:
            # Nothing to choose between, so only where it stands is offered.
            return [] if current is None else [str(current)]
        return [
            value
            for value in field.values
            if override.allows(value) or value == current
        ]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        offered = [
            MODES[value.upper()]
            for value in self._offered(MODE) or ()
            if value.upper() in MODES
        ]
        if HVACMode.OFF not in offered and self._turns("OFF") is not None:
            # It turns off by being told to rather than by a mode of its own.
            offered.append(HVACMode.OFF)
        return offered

    @property
    def fan_modes(self) -> list[str] | None:
        return self._offered(FAN)

    @property
    def swing_modes(self) -> list[str] | None:
        return self._offered(SWING)

    @property
    def available(self) -> bool:
        # A thermostat is a control like any other, and there is nothing to
        # set on an appliance that cannot be reached. The parts it gathers up
        # go unavailable there, and it would look broken staying behind.
        return super().available and self.reachable

    @property
    def min_temp(self) -> float:
        """The lowest it will take, which moves with the rest of the machine.

        The number entity on the same field offers the same, so the two of
        them cannot fall out of step.
        """
        return self._bound("minimum", super().min_temp)

    @property
    def max_temp(self) -> float:
        return self._bound("maximum", super().max_temp)

    @property
    def target_temperature_step(self) -> float | None:
        return (
            self.override_for(TARGET).step
            or self._fields[TARGET].step
            or super().target_temperature_step
        )

    def _bound(self, which: str, fallback: float) -> float:
        for holder in (self.override_for(TARGET), self._fields[TARGET]):
            bound = getattr(holder, which)
            if bound is not None:
                return float(bound)
        return fallback

    @property
    def hvac_mode(self) -> HVACMode | None:
        if str(self.at(STATE)).upper() == "OFF":
            return HVACMode.OFF
        running = self.at(MODE)
        return MODES.get(str(running).upper()) if running is not None else None

    @property
    def current_temperature(self) -> float | None:
        reading = self.at(AMBIENT)
        return float(reading) if isinstance(reading, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        reading = self.at(TARGET)
        return float(reading) if isinstance(reading, (int, float)) else None

    @property
    def fan_mode(self) -> str | None:
        value = self.at(FAN)
        return None if value is None else str(value)

    @property
    def swing_mode(self) -> str | None:
        value = self.at(SWING)
        return None if value is None else str(value)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self._turn(False)
            return
        for word, mapped in MODES.items():
            if mapped is not hvac_mode:
                continue
            spelling = self._spelling(MODE, word)
            if spelling is None:
                continue
            if self.hvac_mode is HVACMode.OFF:
                # A mode is no use to something that is not running.
                await self._turn(True)
            await self.coordinator.send(self._appliance_id, MODE, spelling)
            return

    async def async_turn_on(self) -> None:
        await self._turn(True)

    async def async_turn_off(self) -> None:
        await self._turn(False)

    def _spelling(self, path: str, word: str) -> str | None:
        """How this appliance writes a value, whatever case it writes it in.

        Most of them shout their values and one writes them in camel case, so
        a value is matched without regard to case and sent back in the letters
        the appliance itself used.
        """
        field = self._fields.get(path)
        if field is None:
            return None
        return next((value for value in field.values if value.upper() == word), None)

    def _turns(self, word: str) -> tuple[str, str] | None:
        """The field that takes ON or OFF, and how the appliance writes it.

        Some appliances keep both among the modes they run in and some keep
        them as commands of their own. The mode is preferred, since that is
        the field the state is read back from.
        """
        for path in (MODE, COMMAND):
            spelling = self._spelling(path, word)
            if spelling is not None:
                return path, spelling
        return None

    async def _turn(self, on: bool) -> None:
        word = "ON" if on else "OFF"
        found = self._turns(word)
        if found is None:
            # Nothing to send it to. Turning on and off is only offered where
            # one of the two fields has the word, so this is not reachable
            # from a service call.
            _LOGGER.debug("this appliance has no way of being told %s", word)
            return
        field, spelling = found
        await self.coordinator.send(self._appliance_id, field, spelling)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        wanted = kwargs.get(ATTR_TEMPERATURE)
        if wanted is not None:
            await self.coordinator.send(
                self._appliance_id, TARGET, as_set(float(wanted))
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.send(self._appliance_id, FAN, fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self.coordinator.send(self._appliance_id, SWING, swing_mode)
