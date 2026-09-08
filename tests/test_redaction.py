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

from custom_components.aeg.http import _readable, redact, redact_url

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


def test_a_long_answer_is_cut_but_says_it_was() -> None:
    """The appliance list runs to twelve kilobytes and matters at the far end."""
    long_enough = {"filler": "x" * 30000, "connectionState": "connected"}
    written = _readable(json.dumps(long_enough).encode())
    assert "more characters" in written
    assert len(written) < 30000


def test_an_answer_that_fits_is_left_whole() -> None:
    """Twelve kilobytes fits, which is the point of the room being there."""
    listed = [{"applianceData": {"modelName": "WM"}, "reported": {"a": "b" * 9000}}]
    written = _readable(json.dumps(listed).encode())
    assert "more characters" not in written
    assert "WM" in written


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


def test_hides_a_session_the_answer_sets() -> None:
    """Gigya hands its client identifiers out in a header as well as a body."""
    text = json.dumps(
        redact(
            {
                "Content-Type": "application/json",
                "Set-Cookie": "gmid=gmid.ver4.AtLtiXua1w.55PlvD7cD8eh; Path=/",
                "Server": "cloudflare",
            }
        )
    )
    assert "AtLtiXua1w" not in text
    assert "application/json" in text
    assert "cloudflare" in text


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


def test_a_secret_that_is_not_text_is_hidden_too() -> None:
    """A postcode and a year of birth arrive as numbers, and still say who."""
    profile = redact(
        {
            "zip": 1000,
            "birthYear": 1979,
            "uid": 4815162342,
            "country": "BE",
        }
    )
    text = json.dumps(profile)
    assert "1000" not in text
    assert "1979" not in text
    assert "4815162342" not in text
    # What the account is for stays readable.
    assert "BE" in text


def test_a_secret_hidden_inside_a_list_is_still_hidden() -> None:
    hidden = redact({"phone": ["+3212345678", "+3287654321"]})
    assert "3212345678" not in json.dumps(hidden)


def test_nothing_is_not_a_secret() -> None:
    """An absent field says nothing, so it is left saying nothing."""
    assert redact({"email": None, "password": ""}) == {"email": None, "password": ""}


def test_what_the_appliance_is_complaining_about_stays_readable() -> None:
    """The one thing a report about a misbehaving machine is written for."""
    reported = redact(
        {
            "applianceState": "ALARM",
            "alerts": [{"code": "WATER_LEAK"}, {"code": "DOOR_OPEN"}],
        }
    )
    text = json.dumps(reported)
    assert "WATER_LEAK" in text
    assert "DOOR_OPEN" in text
    assert "hidden" not in text


def test_a_model_naming_its_alerts_in_the_singular_is_read_the_same() -> None:
    assert redact({"alert": [{"code": "E20"}]}) == {"alert": [{"code": "E20"}]}


def test_the_code_that_signs_someone_in_is_still_hidden() -> None:
    """It shares nothing with an alert code but the name."""
    form = redact({"code": "483920", "vToken": "a-token", "gmid": "an-id"})
    assert "483920" not in json.dumps(form)


def test_an_alert_hides_whatever_else_it_carries() -> None:
    """Only the code is the appliance's own vocabulary."""
    hidden = redact(
        {"alerts": [{"code": "WATER_LEAK", "email": "someone@example.com"}]}
    )
    text = json.dumps(hidden)
    assert "WATER_LEAK" in text
    assert "someone@example.com" not in text
