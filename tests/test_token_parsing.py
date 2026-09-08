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

"""Tests for reading a token pair out of a OneAccount answer.

The shapes here are the ones the service actually returned, camelCase from v1
and snake_case from the v2 endpoint the app uses.
"""

import time
from typing import Any

import pytest

from custom_components.aeg.auth import _tokens_from
from custom_components.aeg.errors import AegAuthError


def test_reads_the_v1_answer() -> None:
    """Exactly what the exchange returned, minus the token values."""
    tokens = _tokens_from(
        {
            "accessToken": "an-access-token",
            "expiresIn": 43200,
            "refreshToken": "a-refresh-token",
            "scope": "eluxdeb:*:*:* eluxiot:*:*:* email offline_access",
            "tokenType": "Bearer",
        }
    )
    assert tokens.access_token == "an-access-token"
    assert tokens.refresh_token == "a-refresh-token"
    assert not tokens.expired
    assert tokens.expires_at == pytest.approx(time.time() + 43200, abs=5)


def test_reads_the_v2_answer() -> None:
    tokens = _tokens_from(
        {
            "access_token": "an-access-token",
            "expires_in": 3600,
            "refresh_token": "a-refresh-token",
        }
    )
    assert tokens.access_token == "an-access-token"
    assert tokens.refresh_token == "a-refresh-token"


def test_a_pair_with_no_lifetime_is_already_stale() -> None:
    """Better to renew a token we cannot reason about than to send it."""
    tokens = _tokens_from({"accessToken": "a", "refreshToken": "b"})
    assert tokens.expired


def test_a_lifetime_that_is_not_a_number_is_no_lifetime() -> None:
    """Everything above here expects this module's own errors, not float's."""
    unreadable: list[Any] = ["soon", {"in": 60}, [], ""]
    for given in unreadable:
        tokens = _tokens_from(
            {"accessToken": "a", "refreshToken": "b", "expiresIn": given}
        )
        assert tokens.expired, f"{given!r} was read as a lifetime"


def test_a_lifetime_written_as_words_is_still_read() -> None:
    """The v2 answer sends it as a string."""
    tokens = _tokens_from(
        {"accessToken": "a", "refreshToken": "b", "expiresIn": "43200"}
    )
    assert not tokens.expired


def test_a_missing_half_is_refused() -> None:
    with pytest.raises(AegAuthError):
        _tokens_from({"accessToken": "a", "expiresIn": 60})
    with pytest.raises(AegAuthError):
        _tokens_from({"refreshToken": "b", "expiresIn": 60})
    with pytest.raises(AegAuthError):
        _tokens_from({})
