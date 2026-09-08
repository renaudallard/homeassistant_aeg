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
from .capability import Capability, value_at
from .coordinator import AegCoordinator
from .entity import AegApplianceEntity

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
        mode = fields.get(MODE)
        target = fields.get(TARGET)
        if mode and mode.values and target and target.writable:
            thermostats.append(AegClimate(coordinator, appliance_id, fields))
    add(thermostats)


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

        offered = [MODES[value] for value in fields[MODE].values if value in MODES]
        if HVACMode.OFF not in offered and self._turns("OFF") is not None:
            # It turns off by being told to rather than by a mode of its own.
            offered.append(HVACMode.OFF)
        self._attr_hvac_modes = offered

        target = fields[TARGET]
        if target.minimum is not None:
            self._attr_min_temp = target.minimum
        if target.maximum is not None:
            self._attr_max_temp = target.maximum
        if target.step:
            self._attr_target_temperature_step = target.step

        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if self._turns("OFF") is not None:
            features |= ClimateEntityFeature.TURN_OFF
        if self._turns("ON") is not None:
            features |= ClimateEntityFeature.TURN_ON
        fan = fields.get(FAN)
        if fan and fan.values:
            self._attr_fan_modes = list(fan.values)
            features |= ClimateEntityFeature.FAN_MODE
        swing = fields.get(SWING)
        if swing and swing.values:
            self._attr_swing_modes = list(swing.values)
            features |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = features

    def _at(self, path: str) -> Any:
        appliance = self.appliance
        return None if appliance is None else value_at(appliance.reported, path)

    @property
    def available(self) -> bool:
        # A thermostat is a control like any other, and there is nothing to
        # set on an appliance that cannot be reached. The parts it gathers up
        # go unavailable there, and it would look broken staying behind.
        return super().available and self.reachable

    @property
    def hvac_mode(self) -> HVACMode | None:
        if str(self._at("applianceState")).upper() == "OFF":
            return HVACMode.OFF
        running = self._at(MODE)
        return MODES.get(str(running).upper()) if running is not None else None

    @property
    def current_temperature(self) -> float | None:
        reading = self._at(AMBIENT)
        return float(reading) if isinstance(reading, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        reading = self._at(TARGET)
        return float(reading) if isinstance(reading, (int, float)) else None

    @property
    def fan_mode(self) -> str | None:
        value = self._at(FAN)
        return None if value is None else str(value)

    @property
    def swing_mode(self) -> str | None:
        value = self._at(SWING)
        return None if value is None else str(value)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self._turn(False)
            return
        for word, mapped in MODES.items():
            if mapped is hvac_mode:
                if self.hvac_mode is HVACMode.OFF:
                    # A mode is no use to something that is not running.
                    await self._turn(True)
                await self.coordinator.send(self._appliance_id, MODE, word)
                return

    async def async_turn_on(self) -> None:
        await self._turn(True)

    async def async_turn_off(self) -> None:
        await self._turn(False)

    def _turns(self, word: str) -> str | None:
        """The field that takes ON or OFF as a word, if either of them does.

        Some appliances keep both among the modes they run in and some keep
        them as commands of their own. The mode is preferred, since that is
        the field the state is read back from.
        """
        if word in self._fields[MODE].values:
            return MODE
        command = self._fields.get(COMMAND)
        if command is not None and word in command.values:
            return COMMAND
        return None

    async def _turn(self, on: bool) -> None:
        word = "ON" if on else "OFF"
        field = self._turns(word)
        if field is None:
            # Nothing to send it to. Turning on and off is only offered where
            # one of the two fields has the word, so this is not reachable
            # from a service call.
            _LOGGER.debug("this appliance has no way of being told %s", word)
            return
        await self.coordinator.send(self._appliance_id, field, word)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        wanted = kwargs.get(ATTR_TEMPERATURE)
        if wanted is not None:
            await self.coordinator.send(self._appliance_id, TARGET, float(wanted))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.send(self._appliance_id, FAN, fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self.coordinator.send(self._appliance_id, SWING, swing_mode)
