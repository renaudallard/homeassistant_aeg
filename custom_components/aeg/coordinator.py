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

"""Keeping one account's appliances up to date.

The appliance list carries the reported state of everything on the account, so
one call refreshes them all. Capabilities are fetched once when the entry is
set up: they describe the model rather than its state, and they are large.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AegApi
from .capability import Capability, parse
from .errors import AegAuthError, AegError
from .triggers import Override, evaluate
from .websocket import AegStream, apply

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)
# While the cloud is pushing, polling is only there to catch what a dropped
# connection missed.
SCAN_INTERVAL_STREAMING = timedelta(minutes=10)


@dataclass
class Appliance:
    """One appliance, what it can do and what it is doing."""

    id: str
    name: str
    model: str
    capabilities: list[Capability]
    reported: dict[str, Any]
    connected: bool
    overrides: dict[str, Override]


class AegCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Polls the account and hands out the state of each appliance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AegApi,
        session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="AEG",
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self._session = session
        self._stream: AegStream | None = None
        self._capabilities: dict[str, list[Capability]] = {}

    async def _async_setup(self) -> None:
        """Read what each appliance can do, once."""
        try:
            for entry in await self.api.appliances():
                appliance_id = str(entry.get("applianceId", ""))
                if not appliance_id:
                    continue
                tree = await self.api.capabilities(appliance_id)
                self._capabilities[appliance_id] = parse(tree)
                _LOGGER.debug("%s describes %d fields", appliance_id, len(tree))
        except AegAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AegError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> dict[str, Appliance]:
        try:
            listed = await self.api.appliances()
        except AegAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AegError as err:
            raise UpdateFailed(str(err)) from err

        appliances: dict[str, Appliance] = {}
        for entry in listed:
            appliance_id = str(entry.get("applianceId", ""))
            if not appliance_id:
                continue
            data = entry.get("applianceData") or {}
            properties = entry.get("properties") or {}
            appliances[appliance_id] = Appliance(
                id=appliance_id,
                name=str(data.get("applianceName") or "AEG appliance"),
                model=str(data.get("modelName") or "appliance"),
                capabilities=self._capabilities.get(appliance_id, []),
                reported=properties.get("reported") or {},
                connected=entry.get("connectionState") == "connected",
                overrides={},
            )
        self._refresh_overrides(appliances)
        return appliances

    def _refresh_overrides(self, appliances: dict[str, Appliance]) -> None:
        """Work out what each appliance will accept in the state it is in."""
        for appliance in appliances.values():
            appliance.overrides = evaluate(appliance.capabilities, appliance.reported)

    def start_stream(self, url: str) -> None:
        """Ask the cloud to push changes rather than waiting to be asked."""
        if self._stream is not None or not url or not self.data:
            return
        self._stream = AegStream(
            self._session,
            url,
            self.api.authorization,
            self.api.seconds_until_renewal,
            list(self.data),
            self._pushed,
            self._streaming,
        )
        self._stream.start()

    async def stop_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await stream.stop()

    def _pushed(self, message: dict[str, Any]) -> None:
        """Fold a pushed change into what we hold and tell the entities."""
        touched = apply(
            message, {key: value.reported for key, value in self.data.items()}
        )
        if touched:
            # What the appliance will accept moves with its state.
            self._refresh_overrides(self.data)
            self.async_set_updated_data(self.data)

    def _streaming(self, connected: bool) -> None:
        # Polling stays as the safety net for whatever a drop missed.
        self.update_interval = SCAN_INTERVAL_STREAMING if connected else SCAN_INTERVAL

    async def send(self, appliance_id: str, path: str, value: Any) -> None:
        """Send one field, nested the way the appliance reports it back."""
        command: dict[str, Any] = {}
        target = command
        segments = path.split("/")
        for segment in segments[:-1]:
            target = target.setdefault(segment, {})
        target[segments[-1]] = value
        await self.api.send_command(appliance_id, command)
        await self.async_request_refresh()
