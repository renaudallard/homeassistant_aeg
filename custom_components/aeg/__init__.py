"""AEG appliance integration.

An entry owns one AEG account and the appliances on it. The token pair lives in
the entry rather than in memory, because renewing rotates the refresh token and
a pair that is not written back leaves the account unreachable after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_COUNTRY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AegApi
from .auth import AegAuth, Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
)
from .errors import AegAuthError, AegError

# Entities come once the capability tree is mapped.
PLATFORMS: list[Platform] = []


@dataclass
class AegData:
    """What an entry needs while it is loaded."""

    api: AegApi


type AegConfigEntry = ConfigEntry[AegData]


async def async_setup_entry(hass: HomeAssistant, entry: AegConfigEntry) -> bool:
    """Set up an AEG account."""
    session = async_get_clientsession(hass)
    country = entry.data[CONF_COUNTRY]
    auth = AegAuth(session, country)
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

    # One call proves the stored tokens still work, so a revoked account asks
    # for reauthentication now rather than when the first entity updates.
    try:
        await api.appliances()
    except AegAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AegError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = AegData(api=api)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AegConfigEntry) -> bool:
    """Unload an AEG account."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
