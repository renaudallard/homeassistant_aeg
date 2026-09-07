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

"""Tests for renewing the access token.

The service refuses to mint a token when it issued one moments ago, answering
429 with cas_3404. The app recovers by keeping the token it holds, and so does
this, because the margin that triggers a renewal is shorter than the life left
in the token.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.aeg.api import AegApi
from custom_components.aeg.auth import Tokens
from custom_components.aeg.errors import AegTooManyRequests


def _api(auth: AsyncMock, tokens: Tokens) -> AegApi:
    return AegApi(MagicMock(), auth, tokens, "https://api.eu.ocp.electrolux.one", "BE")


async def test_a_refused_renewal_keeps_a_token_that_still_works() -> None:
    auth = AsyncMock()
    auth.refresh.side_effect = AegTooManyRequests("too frequent")
    # Inside the renewal margin, so a renewal is attempted, but not yet expired.
    tokens = Tokens("an-access-token", "a-refresh-token", time.time() + 30)
    api = _api(auth, tokens)

    assert await api._access_token() == "an-access-token"
    auth.refresh.assert_awaited_once()


async def test_a_refused_renewal_is_fatal_once_the_token_is_dead() -> None:
    auth = AsyncMock()
    auth.refresh.side_effect = AegTooManyRequests("too frequent")
    tokens = Tokens("an-access-token", "a-refresh-token", time.time() - 10)
    api = _api(auth, tokens)

    with pytest.raises(AegTooManyRequests):
        await api._access_token()


async def test_a_renewed_pair_is_handed_to_the_listener() -> None:
    """Whatever stores the pair has to see the rotation, or the next start fails."""
    renewed = Tokens("a-new-token", "a-new-refresh-token", time.time() + 43200)
    auth = AsyncMock()
    auth.refresh.return_value = renewed
    seen: list[Tokens] = []

    async def remember(tokens: Tokens) -> None:
        seen.append(tokens)

    api = AegApi(
        MagicMock(),
        auth,
        Tokens("old", "old-refresh", time.time() - 1),
        "https://api.eu.ocp.electrolux.one",
        "BE",
        on_tokens=remember,
    )

    assert await api._access_token() == "a-new-token"
    assert seen == [renewed]
    assert api.tokens is renewed


async def test_a_live_token_is_used_without_asking_for_another() -> None:
    auth = AsyncMock()
    api = _api(auth, Tokens("an-access-token", "a-refresh-token", time.time() + 43200))

    assert await api._access_token() == "an-access-token"
    auth.refresh.assert_not_awaited()
