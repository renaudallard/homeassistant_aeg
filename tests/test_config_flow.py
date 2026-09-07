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

"""Tests for the config flow, driven through Home Assistant itself.

The cloud is mocked at the two classes the flow talks to, so what is under test
is the flow: which step follows which, what reaches the config entry, and which
message the user gets when a step fails.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_CODE, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aeg.auth import IdentityProvider, Tokens
from custom_components.aeg.const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_WS_URL,
    DOMAIN,
)
from custom_components.aeg.errors import AegAuthError, AegConnectionError
from custom_components.aeg.gigya import INVALID_CREDENTIALS, GigyaIds, GigyaSession

EMAIL = "someone@example.com"
COUNTRY = "FR"
PASSWORD = "hunter2"

PROVIDER = IdentityProvider(
    domain="eu1.gigya.com",
    api_key="an-api-key",
    brand="aeg",
    http_base_url="https://api.eu.ocp.electrolux.one",
    ws_base_url="wss://ws.eu.ocp.electrolux.one",
)
TOKENS = Tokens(
    access_token="an-access-token",
    refresh_token="a-refresh-token",
    expires_at=4102444800.0,
)
SESSION = GigyaSession(token="a-session-token", secret="a-session-secret")
IDS = GigyaIds(gmid="a-gmid", ucid="a-ucid")


@pytest.fixture
def auth() -> AsyncMock:
    mock = AsyncMock()
    mock.identity_provider.return_value = PROVIDER
    mock.exchange.return_value = TOKENS
    return mock


@pytest.fixture
def client() -> AsyncMock:
    mock = AsyncMock()
    mock.ids.return_value = IDS
    mock.login.return_value = SESSION
    mock.login_with_otp.return_value = SESSION
    mock.send_otp_code.return_value = "a-vtoken"
    mock.jwt.return_value = "an-id-token"
    return mock


@contextmanager
def cloud(auth: AsyncMock, client: AsyncMock) -> Iterator[None]:
    """Stand in for both services, and for setting the entry up afterwards."""
    with (
        patch("custom_components.aeg.config_flow.AegAuth", return_value=auth),
        patch("custom_components.aeg.config_flow.GigyaClient", return_value=client),
        patch("custom_components.aeg.async_setup_entry", return_value=True),
    ):
        yield


async def start(hass: HomeAssistant) -> str:
    """Open the flow and return its id, having checked it offers the menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert set(cast(list[str], result["menu_options"])) == {"password", "email_code"}
    return result["flow_id"]


async def test_password_signs_in(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    flow_id = await start(hass)
    with cloud(auth, client):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "password"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "password"

        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["data"] == {
        CONF_EMAIL: EMAIL,
        CONF_COUNTRY: COUNTRY,
        CONF_BASE_URL: PROVIDER.http_base_url,
        CONF_WS_URL: PROVIDER.ws_base_url,
        CONF_ACCESS_TOKEN: TOKENS.access_token,
        CONF_REFRESH_TOKEN: TOKENS.refresh_token,
        CONF_EXPIRES_AT: TOKENS.expires_at,
    }
    client.login.assert_awaited_once_with(EMAIL, PASSWORD, IDS)


async def test_wrong_password_points_at_the_code_path(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    """A rejected password is the cue that the account may have none."""
    flow_id = await start(hass)
    client.login.side_effect = AegAuthError("nope", INVALID_CREDENTIALS)
    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "password"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_password"}


async def test_other_rejection_is_not_a_wrong_password(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    flow_id = await start(hass)
    client.login.side_effect = AegAuthError("disabled", 403041)
    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "password"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY, CONF_PASSWORD: PASSWORD},
        )

    assert result["errors"] == {"base": "invalid_auth"}


async def test_unreachable_service_can_be_retried(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    flow_id = await start(hass)
    auth.identity_provider.side_effect = AegConnectionError("down")
    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "password"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_mailed_code_signs_in(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    flow_id = await start(hass)
    with cloud(auth, client):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "email_code"}
        )
        assert result["step_id"] == "email_code"

        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "code"

        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_CODE: "123456"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    client.send_otp_code.assert_awaited_once_with(EMAIL, IDS)
    client.login_with_otp.assert_awaited_once_with("123456", "a-vtoken", IDS)


async def test_a_bad_code_can_be_retyped(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    flow_id = await start(hass)
    client.login_with_otp.side_effect = AegAuthError("expired", 400006)
    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "email_code"}
        )
        await hass.config_entries.flow.async_configure(
            flow_id, {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_CODE: "000000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"
    assert result["errors"] == {"base": "invalid_code"}


async def test_the_same_account_is_not_added_twice(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    """The address identifies the account, whatever case it is typed in."""
    MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, data={CONF_EMAIL: EMAIL}
    ).add_to_hass(hass)

    flow_id = await start(hass)
    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            flow_id, {"next_step_id": "password"}
        )
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            {
                CONF_EMAIL: EMAIL.upper(),
                CONF_COUNTRY: COUNTRY,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_the_entry_in_place(
    hass: HomeAssistant, auth: AsyncMock, client: AsyncMock
) -> None:
    """Signing in again replaces the tokens without adding a second account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=EMAIL,
        data={
            CONF_EMAIL: EMAIL,
            CONF_COUNTRY: COUNTRY,
            CONF_BASE_URL: PROVIDER.http_base_url,
            CONF_ACCESS_TOKEN: "a-stale-token",
            CONF_REFRESH_TOKEN: "a-stale-refresh-token",
            CONF_EXPIRES_AT: 0.0,
        },
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.MENU

    with cloud(auth, client):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "password"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: EMAIL, CONF_COUNTRY: COUNTRY, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_TOKEN] == TOKENS.access_token
    assert entry.data[CONF_REFRESH_TOKEN] == TOKENS.refresh_token
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
