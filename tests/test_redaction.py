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

"""Tests that debug logging gives nothing away.

The output is meant to be pasted into a bug report, so credentials, tokens and
the identity of the account and its appliances have to be gone. The shapes here
are the ones a real account produced.
"""

import json

from custom_components.aeg.http import redact, redact_url

APPLIANCE = "914505616_00:54600049-443E07743904"
BASE = "https://api.eu.ocp.electrolux.one/appliance/api/v2/appliances"


def test_hides_an_appliance_id_in_a_path() -> None:
    assert redact_url(f"{BASE}/{APPLIANCE}/capabilities") == (
        f"{BASE}/<appliance id hidden>/capabilities"
    )
    assert redact_url(f"{BASE}/{APPLIANCE}") == f"{BASE}/<appliance id hidden>"
    assert redact_url(f"{BASE}/{APPLIANCE}/command") == (
        f"{BASE}/<appliance id hidden>/command"
    )


def test_leaves_the_route_alone() -> None:
    """Words after appliances are part of the route, not an identifier."""
    assert redact_url(BASE) == BASE
    assert redact_url(f"{BASE}/info") == f"{BASE}/info"
    assert "hidden" not in redact_url(
        "https://api.ocp.electrolux.one/one-account-authorization/api/v1/token"
    )


def test_hides_an_appliance_id_in_a_body() -> None:
    listed = redact(
        [
            {
                "applianceId": APPLIANCE,
                "applianceData": {"applianceName": "Lave-linge", "modelName": "WM"},
                "status": "enabled",
            }
        ]
    )
    text = json.dumps(listed)
    assert APPLIANCE not in text
    # What the appliance is stays readable, only which one it is goes.
    assert "WM" in text
    assert "enabled" in text


def test_hides_everything_secret_in_a_token_answer() -> None:
    answer = redact(
        {
            "accessToken": "a-real-token",
            "refreshToken": "a-real-refresh-token",
            "expiresIn": 43200,
            "scope": "eluxdeb:*:*:* eluxiot:*:*:* email offline_access",
            "tokenType": "Bearer",
        }
    )
    text = json.dumps(answer)
    assert "a-real-token" not in text
    assert "a-real-refresh-token" not in text
    # The parts that say what happened are still there.
    assert "43200" in text
    assert "offline_access" in text


def test_hides_who_the_account_belongs_to() -> None:
    """The Gigya login answer carries a name, a town and a postcode."""
    text = json.dumps(
        redact(
            {
                "UID": "68193f82504b46c189b6803592d6e840",
                "UIDSignature": "S/6IBYvZq2Hfyy/YyTLAIEVZftE=",
                "isActive": True,
                "loginProvider": "site",
                "profile": {
                    "firstName": "Renaud",
                    "lastName": "ALLARD",
                    "city": "Braine-l'Alleud",
                    "country": "BE",
                    "email": "someone@example.com",
                    "zip": "1420",
                },
            }
        )
    )
    for personal in (
        "68193f82504b46c189b6803592d6e840",
        "S/6IBYvZq2Hfyy/YyTLAIEVZftE=",
        "Renaud",
        "ALLARD",
        "Braine",
        "someone@example.com",
        "1420",
    ):
        assert personal not in text
    # Whether the account works, and where it lives, still readable.
    assert "isActive" in text
    assert "site" in text
    assert "BE" in text


def test_hides_the_client_identifiers_gigya_hands_out() -> None:
    text = json.dumps(
        redact(
            {
                "gmid": "gmid.ver4.AtLtiXua1w.55PlvD7cD8eh",
                "gcid": "gmid.ver4.AtLtiXua1w.PoRGq7Xw6yTA",
                "ucid": "a-ucid-value",
                "errorCode": 0,
            }
        )
    )
    assert "AtLtiXua1w" not in text
    assert "a-ucid-value" not in text
    assert "errorCode" in text


def test_appliance_state_is_not_mistaken_for_a_profile_field() -> None:
    """A log with the appliance state redacted out would be useless."""
    text = json.dumps(
        redact({"doorState": "OPEN", "state": "RUNNING", "cyclePhase": "MAIN_WASH"})
    )
    assert "OPEN" in text
    assert "RUNNING" in text
    assert "MAIN_WASH" in text


def test_hides_the_account_and_its_credentials() -> None:
    text = json.dumps(
        redact(
            {
                "loginID": "someone@example.com",
                "password": "hunter2",
                "sig": "an-hmac",
                "apiKey": "an-api-key",
                "sessionSecret": "a-session-secret",
                "profile": {"email": "someone@example.com", "country": "BE"},
            }
        )
    )
    for secret in (
        "someone@example.com",
        "hunter2",
        "an-hmac",
        "an-api-key",
        "a-session-secret",
    ):
        assert secret not in text
    assert "BE" in text
