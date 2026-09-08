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

"""Readings from an appliance."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import AegConfigEntry
from .capability import SENSOR, Capability, counts_down, is_duration
from .coordinator import AegCoordinator
from .entity import AegEntity, degrees, fields


async def async_setup_entry(
    hass: HomeAssistant, entry: AegConfigEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    readings: list[SensorEntity] = []
    for appliance_id, capability in fields(coordinator, SENSOR):
        readings.append(AegSensor(coordinator, appliance_id, capability))
        if is_duration(capability):
            # The seconds are what the appliance says; the clock is what
            # anyone actually wants to read.
            readings.append(AegDuration(coordinator, appliance_id, capability))
        if counts_down(capability):
            readings.append(AegFinishesAt(coordinator, appliance_id, capability))
    add(readings)


class AegSensor(AegEntity, SensorEntity):
    """A field that can be read but not set."""

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        if is_duration(capability):
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        elif capability.kind == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = degrees(capability)
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        value = self.reported
        if isinstance(value, (dict, list)):
            # Nothing sensible to show for a structure, and a state has to fit
            # in 255 characters.
            return None
        return value


class AegDuration(AegEntity, SensorEntity):
    """The same length of time, written as a clock reads it.

    Time left counts down here rather than waiting to be told. It cannot drift
    from what the appliance says, because every figure that arrives replaces
    the one being counted from: pick a shorter programme and the clock is on
    the new time as soon as the cloud mentions it, not a minute later and not
    somewhere between the two.
    """

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._attr_unique_id = f"{appliance_id}-{capability.path}-formatted"
        # A name of its own, which wins over anything the field is called.
        self._attr_name = f"{self.plain_name} formatted"
        self._ticks = counts_down(capability)
        self._seen: float | None = None
        self._seen_at = time.monotonic()
        self._shown: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remember()
        self._shown = self._clock()
        if self._ticks:
            self.async_on_remove(
                async_track_time_interval(self.hass, self._tick, timedelta(seconds=1))
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        # The appliance has spoken, so count from what it just said.
        self._remember()
        super()._handle_coordinator_update()
        self._shown = self._clock()

    def _remember(self) -> None:
        """Take a new figure to count down from, when there is a new one.

        Anything the appliance says brings every entity round, not only the
        ones it said something about. Counting afresh from a figure that has
        not moved would stand the clock still, and put it back where it was
        every time anything else changed.
        """
        value = self.reported
        usable = isinstance(value, (int, float)) and not isinstance(value, bool)
        fresh = float(value) if usable else None
        if fresh == self._seen:
            return
        self._seen = fresh
        self._seen_at = time.monotonic()

    @callback
    def _tick(self, now: Any) -> None:
        """Write the clock out again, but only when it says something new."""
        current = self._clock()
        if current != self._shown:
            self._shown = current
            self.async_write_ha_state()

    @property
    def _running(self) -> bool:
        """Whether the appliance is doing the thing it is counting down to.

        A washing machine that has finished turns itself off and puts the
        length of the programme it is set to back where the time left was.
        Counting that down would show a wash that is not happening.
        """
        return self.running

    def _stale_after(self) -> float:
        """How long a figure can be counted down from before it is guesswork.

        Two turns of whatever the account is being looked at on. Anything
        older than that has been overtaken by something not arriving.
        """
        interval = self.coordinator.update_interval
        return 2 * interval.total_seconds() if interval else 120.0

    def _clock(self) -> str | None:
        seconds = self._seen
        # A washing machine says -1 for a time it does not have, such as the
        # end of a cycle it is not running.
        if seconds is None or seconds < 0:
            return None
        if self._ticks and self._running:
            elapsed = time.monotonic() - self._seen_at
            if elapsed > self._stale_after():
                # Counting down from a figure this old would end at nothing
                # left and say so as though it were a fact.
                return None
            seconds = max(0.0, seconds - elapsed)
        whole = int(seconds)
        return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"

    @property
    def native_value(self) -> str | None:
        return self._clock()


class AegFinishesAt(AegEntity, SensorEntity):
    """When the time left runs out.

    A countdown written as a clock only moves when the cloud says something,
    which is now and then rather than every second. The moment it finishes does
    not move at all, and Home Assistant counts down to a timestamp on its own,
    so this is the one that reads live without writing a state a second.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: AegCoordinator, appliance_id: str, capability: Capability
    ) -> None:
        super().__init__(coordinator, appliance_id, capability)
        self._attr_unique_id = f"{appliance_id}-{capability.path}-at"
        # Named for what it is rather than for the field it comes from, since
        # an appliance has one thing it is counting down to.
        self._attr_name = "Finishes at"
        self._at: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._work_out_when()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._work_out_when()
        super()._handle_coordinator_update()

    def _work_out_when(self) -> None:
        """Fix the finish to a moment, from the seconds left as they arrive.

        Only while the appliance is running: a machine that has finished puts
        the length of its next programme where the time left was, and a finish
        worked out from that is for a wash nobody has started.
        """
        seconds = self.reported
        usable = isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        if not self.running or not usable or seconds < 0:
            self._at = None
            return
        # To the second: the appliance counts in seconds, and a finish that
        # wandered by a fraction on every update would be written out again
        # each time for no reason.
        self._at = (dt_util.utcnow() + timedelta(seconds=int(seconds))).replace(
            microsecond=0
        )

    @property
    def native_value(self) -> datetime | None:
        return self._at
