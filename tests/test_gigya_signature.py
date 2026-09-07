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

"""Tests for the Gigya request signature.

The expected values were produced by cross checking against pyelectroluxocp,
an independent client that is known to work against the live Gigya tenant, so
they pin our implementation to behaviour the service already accepts.
"""

from custom_components.aeg.gigya import _normalized_url, _signature_base, sign_request

SECRET = "aGVsbG8gd29ybGQgc2VjcmV0IGtleSE="


def test_signs_a_get_jwt_request() -> None:
    params = {
        "apiKey": "PEdfAP7N7sUc95GJPePDU54e2Pybbt6DZtdww7dz",
        "fields": "country",
        "format": "json",
        "gmid": "gmid.ver4.AcbH_x",
        "httpStatusCodes": "true",
        "nonce": "1757248800000_123456789",
        "oauth_token": "st2.s.AcbH.abc-def_ghi",
        "sdk": "Android_7.1.2",
        "targetEnv": "mobile",
        "timestamp": "1757248800",
        "ucid": "abc123",
    }
    signature = sign_request(
        SECRET, "POST", "https://accounts.eu1.gigya.com/accounts.getJWT", params
    )
    assert signature == "u7vSgvnHdNr4Xx7wFKIA/OoNvSc="


def test_encodes_reserved_characters_in_values() -> None:
    params = {
        "loginID": "user+tag@example.com",
        "password": "a b/c~d=e&f",
        "note": "café",
        "apiKey": "K",
    }
    signature = sign_request(
        SECRET, "POST", "https://accounts.eu1.gigya.com/accounts.login", params
    )
    assert signature == "cDvGMlFtXQv1djzYd/JNV0lQ/C0="


def test_drops_an_explicit_default_port() -> None:
    params = {"a": "1", "b": "2"}
    signature = sign_request(
        SECRET, "POST", "https://accounts.eu1.gigya.com:443/accounts.getJWT", params
    )
    assert signature == "wsCD9Fwt3hueGTmguWvZR2sfo6o="


def test_normalizes_scheme_host_and_port() -> None:
    assert (
        _normalized_url("HTTPS://Accounts.EU1.Gigya.com:443/accounts.getJWT?x=1")
        == "https://accounts.eu1.gigya.com/accounts.getJWT"
    )
    assert (
        _normalized_url("https://accounts.eu1.gigya.com:8443/accounts.getJWT")
        == "https://accounts.eu1.gigya.com:8443/accounts.getJWT"
    )


def test_base_string_sorts_parameters() -> None:
    base = _signature_base(
        "post", "https://accounts.eu1.gigya.com/accounts.login", {"b": "2", "a": "1"}
    )
    assert base == (
        "POST&https%3A%2F%2Faccounts.eu1.gigya.com%2Faccounts.login&a%3D1%26b%3D2"
    )
