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

"""Tests for reading the country out of the Gigya JWT.

The claims are base64url without padding, so the decode has to put it back.
These cover payload lengths needing each amount of padding.
"""

from custom_components.aeg.auth import _jwt_country


def test_reads_country_fr() -> None:
    assert (
        _jwt_country(
            "eyJhbGciOiAiUlMyNTYifQ.eyJjb3VudHJ5IjogIkZSIiwgInN1YiI6ICJ1c2VyIn0.signature"
        )
        == "FR"
    )


def test_reads_country_be() -> None:
    assert (
        _jwt_country(
            "eyJhbGciOiAiUlMyNTYifQ.eyJjb3VudHJ5IjogIkJFIiwgInN1YiI6ICJ1c2VyeCJ9.signature"
        )
        == "BE"
    )


def test_reads_country_se() -> None:
    assert (
        _jwt_country(
            "eyJhbGciOiAiUlMyNTYifQ.eyJjb3VudHJ5IjogIlNFIiwgInN1YiI6ICJ1c2VyeHkifQ.signature"
        )
        == "SE"
    )


def test_survives_a_token_that_is_not_a_jwt() -> None:
    assert _jwt_country("not-a-jwt") is None
    assert _jwt_country("") is None
    assert _jwt_country("a.!!!not-base64!!!.c") is None


def test_returns_none_when_there_is_no_country_claim() -> None:
    assert _jwt_country("eyJhbGciOiAiUlMyNTYifQ.eyJzdWIiOiAidXNlciJ9.signature") is None
