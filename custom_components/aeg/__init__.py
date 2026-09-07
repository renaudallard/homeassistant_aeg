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

"""AEG appliance integration.

An entry owns one AEG account and the appliances on it. The token pair lives in
the entry rather than in memory, because renewing rotates the refresh token and
a pair that is not written back leaves the account unreachable after a restart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_COUNTRY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AegApi
from .auth import AegAuth, Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_WS_URL,
)
from .coordinator import AegCoordinator
from .errors import AegError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class AegData:
    """What an entry needs while it is loaded."""

    api: AegApi
    coordinator: AegCoordinator


type AegConfigEntry = ConfigEntry[AegData]


async def async_setup_entry(hass: HomeAssistant, entry: AegConfigEntry) -> bool:
    """Set up an AEG account."""
    session = async_get_clientsession(hass)
    country = entry.data[CONF_COUNTRY]
    auth = AegAuth(session, country, entry.data[CONF_BASE_URL])
    tokens = Tokens(
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data[CONF_EXPIRES_AT],
    )

    async def store(renewed: Tokens) -> None:
        """Write a renewed pair back to the entry."""
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: renewed.access_token,
                CONF_REFRESH_TOKEN: renewed.refresh_token,
                CONF_EXPIRES_AT: renewed.expires_at,
            },
        )

    api = AegApi(
        session, auth, tokens, entry.data[CONF_BASE_URL], country, on_tokens=store
    )

    # The first refresh reads what every appliance can do and what it is
    # doing, and proves the stored tokens still work while it is at it.
    coordinator = AegCoordinator(hass, entry, api, session)
    await coordinator.async_config_entry_first_refresh()

    coordinator.start_stream(await _stream_url(hass, entry, auth))

    entry.runtime_data = AegData(api=api, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _stream_url(hass: HomeAssistant, entry: AegConfigEntry, auth: AegAuth) -> str:
    """Where the cloud pushes changes for this account.

    Entries made before there was a stream do not have it, so it is looked up
    once and kept. Without it the integration polls, which is worse but works.
    """
    stored = entry.data.get(CONF_WS_URL)
    if stored:
        return str(stored)
    try:
        url = (await auth.identity_provider()).ws_base_url
    except AegError as err:
        _LOGGER.debug("no endpoint to stream from, polling instead: %s", err)
        return ""
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_WS_URL: url})
    return url


async def async_unload_entry(hass: HomeAssistant, entry: AegConfigEntry) -> bool:
    """Unload an AEG account."""
    await entry.runtime_data.coordinator.stop_stream()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
