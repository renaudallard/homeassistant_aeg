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

"""Config flow for the AEG integration.

Which way in an account has depends on the account: one with a password signs
in directly, one without can only be reached with a code mailed to it. Nothing
says in advance which applies, so the flow asks rather than guesses.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_CODE, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    CountrySelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import gigya
from .auth import AegAuth, IdentityProvider
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_WS_URL,
    DOMAIN,
)
from .errors import AegAuthError, AegConnectionError
from .gigya import GigyaClient, GigyaIds, GigyaSession

_LOGGER = logging.getLogger(__name__)


def _account_schema(email: str, country: str, with_password: bool) -> vol.Schema:
    """Ask for the account, and for the password when that is the way in."""
    fields: dict[Any, Any] = {
        vol.Required(CONF_EMAIL, default=email): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_COUNTRY, default=country): CountrySelector(),
    }
    if with_password:
        fields[vol.Required(CONF_PASSWORD)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    return vol.Schema(fields)


class AegConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through signing in to an AEG account."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._country = ""
        self._vtoken = ""
        self._auth: AegAuth | None = None
        self._client: GigyaClient | None = None
        self._ids: GigyaIds | None = None
        self._provider: IdentityProvider | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which way in this account has."""
        return self.async_show_menu(
            step_id="user", menu_options=["password", "email_code"]
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with a password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._country = user_input[CONF_COUNTRY]
            try:
                await self._prepare()
                session = await self._login_with_password(user_input[CONF_PASSWORD])
                account = await self._account(session)
            except AegAuthError as err:
                _LOGGER.warning("signing in failed: %s", err)
                errors["base"] = (
                    "invalid_password"
                    if err.code == gigya.INVALID_CREDENTIALS
                    else "invalid_auth"
                )
            except AegConnectionError as err:
                _LOGGER.warning("could not reach the service: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("unexpected failure while signing in")
                errors["base"] = "unknown"
            else:
                return await self._finish(account)
        return self.async_show_form(
            step_id="password",
            data_schema=_account_schema(self._email, self._country, True),
            errors=errors,
        )

    async def async_step_email_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mail a code to the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._country = user_input[CONF_COUNTRY]
            try:
                await self._prepare()
                self._vtoken = await self._send_code()
            except AegAuthError as err:
                _LOGGER.warning("requesting a code failed: %s", err)
                errors["base"] = "invalid_auth"
            except AegConnectionError as err:
                _LOGGER.warning("could not reach the service: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("unexpected failure while requesting a code")
                errors["base"] = "unknown"
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="email_code",
            data_schema=_account_schema(self._email, self._country, False),
            errors=errors,
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Take the code out of the mail and finish signing in."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                session = await self._login_with_code(user_input[CONF_CODE])
                account = await self._account(session)
            except AegAuthError as err:
                _LOGGER.warning("the code was not accepted: %s", err)
                errors["base"] = "invalid_code"
            except AegConnectionError as err:
                _LOGGER.warning("could not reach the service: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("unexpected failure while checking the code")
                errors["base"] = "unknown"
            else:
                return await self._finish(account)
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Sign in again for an entry whose tokens stopped working."""
        self._email = entry_data[CONF_EMAIL]
        self._country = entry_data[CONF_COUNTRY]
        return await self.async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in again without being asked to.

        The country is the one thing about an entry that can be wrong rather
        than stale: it picks the server the appliances are on, and an account
        registered elsewhere finds none. Setting the entry up again would find
        them, at the cost of every entity id and all the history on it, so it
        is offered here instead.
        """
        entry = self._get_reconfigure_entry()
        self._email = entry.data[CONF_EMAIL]
        self._country = entry.data[CONF_COUNTRY]
        return await self.async_step_user()

    async def _prepare(self) -> None:
        """Find where the account lives and open a Gigya client for it."""
        session = async_get_clientsession(self.hass)
        auth = AegAuth(session, self._country)
        provider = await auth.identity_provider()
        client = GigyaClient(session, provider.api_key, provider.domain)
        self._auth = auth
        self._provider = provider
        self._client = client
        self._ids = await client.ids()

    async def _login_with_password(self, password: str) -> GigyaSession:
        if self._client is None or self._ids is None:
            raise AegConnectionError("the account lookup did not finish")
        return await self._client.login(self._email, password, self._ids)

    async def _send_code(self) -> str:
        if self._client is None or self._ids is None:
            raise AegConnectionError("the account lookup did not finish")
        return await self._client.send_otp_code(self._email, self._ids)

    async def _login_with_code(self, code: str) -> GigyaSession:
        if self._client is None or self._ids is None:
            raise AegConnectionError("the account lookup did not finish")
        return await self._client.login_with_otp(code, self._vtoken, self._ids)

    async def _account(self, session: GigyaSession) -> dict[str, Any]:
        """Trade the Gigya session for tokens, and shape what an entry holds.

        Everything here can fail on the way, so it is done where the step can
        still show the form again. Writing the entry is not: refusing to add
        the same account twice is done by raising, and that would be caught
        here and reported as something having gone wrong.
        """
        if (
            self._client is None
            or self._ids is None
            or self._provider is None
            or self._auth is None
        ):
            raise AegConnectionError("the account lookup did not finish")
        id_token = await self._client.jwt(session, self._ids)
        tokens = await self._auth.exchange(id_token)
        return {
            CONF_EMAIL: self._email,
            CONF_COUNTRY: self._country,
            CONF_BASE_URL: self._provider.http_base_url,
            CONF_WS_URL: self._provider.ws_base_url,
            CONF_ACCESS_TOKEN: tokens.access_token,
            CONF_REFRESH_TOKEN: tokens.refresh_token,
            CONF_EXPIRES_AT: tokens.expires_at,
        }

    def _existing(self) -> ConfigEntry | None:
        """The entry this sign in is for, when it is for one already there."""
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry()
        if self.source == SOURCE_RECONFIGURE:
            return self._get_reconfigure_entry()
        return None

    async def _finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Write the account into an entry, or back into the one it is for."""
        await self.async_set_unique_id(self._email.lower())
        existing = self._existing()
        if existing is not None:
            # Signing in as somebody else would put one account's tokens under
            # another's name and take its appliances with them.
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(existing, data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._email, data=data)
