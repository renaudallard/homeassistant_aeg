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

"""Tests for folding pushed changes into the state we hold.

A push carries only what moved, so the whole of it has to be merged rather than
put in place. The messages here are the shapes the cloud really sends.
"""

from typing import Any

from custom_components.aeg.websocket import apply, merge


def _message(appliance_id: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ConnectionId": "a-connection",
        "Api": "STREAM",
        "Version": "2.0",
        "Payload": {"Appliances": [{"ApplianceId": appliance_id, "Metrics": metrics}]},
    }


def test_a_pushed_field_replaces_what_we_hold() -> None:
    state = {"an-appliance": {"doorState": "CLOSED", "timeToEnd": 4080}}
    touched = apply(
        _message(
            "an-appliance",
            [
                {
                    "Name": "doorState",
                    "Value": "OPEN",
                    "Timestamp": "2026-09-07T00:00:00Z",
                },
                {"Name": "timeToEnd", "Value": -1, "Timestamp": "2026-09-07T00:00:00Z"},
            ],
        ),
        state,
    )
    assert touched == {"an-appliance"}
    assert state["an-appliance"] == {"doorState": "OPEN", "timeToEnd": -1}


def test_a_group_keeps_the_members_that_did_not_move() -> None:
    """A push of userSelections carries only the fields that changed."""
    state = {
        "an-appliance": {
            "userSelections": {
                "analogTemperature": "40_CELSIUS",
                "analogSpinSpeed": "1400_RPM",
                "programUID": "COTTON_PR_ECO40-60",
            }
        }
    }
    apply(
        _message(
            "an-appliance",
            [
                {
                    "Name": "userSelections",
                    "Value": {
                        "analogTemperature": "30_CELSIUS",
                        "programUID": "QUICK_20_MIN_PR_20MIN3KG",
                    },
                    "Timestamp": "2026-09-07T00:00:00Z",
                }
            ],
        ),
        state,
    )
    assert state["an-appliance"]["userSelections"] == {
        "analogTemperature": "30_CELSIUS",
        "analogSpinSpeed": "1400_RPM",
        "programUID": "QUICK_20_MIN_PR_20MIN3KG",
    }


def test_a_push_for_something_else_is_ignored() -> None:
    state = {"an-appliance": {"doorState": "CLOSED"}}
    touched = apply(
        _message("another-appliance", [{"Name": "doorState", "Value": "OPEN"}]), state
    )
    assert touched == set()
    assert state["an-appliance"] == {"doorState": "CLOSED"}


def test_a_message_with_nothing_in_it_changes_nothing() -> None:
    state = {"an-appliance": {"doorState": "CLOSED"}}
    empty: list[dict[str, Any]] = [{}, {"Payload": {}}, {"Payload": {"Appliances": []}}]
    for message in empty:
        assert apply(message, state) == set()
    assert state["an-appliance"] == {"doorState": "CLOSED"}


def test_a_group_arriving_whole_replaces_a_plain_value() -> None:
    """Merging only applies where both sides are groups."""
    held: dict[str, Any] = {"userSelections": "UNAVAILABLE"}
    merge(held, "userSelections", {"analogTemperature": "40_CELSIUS"})
    assert held == {"userSelections": {"analogTemperature": "40_CELSIUS"}}


def test_a_group_nested_two_deep_is_still_merged() -> None:
    held: dict[str, Any] = {"a": {"b": {"keep": 1, "change": 1}}}
    merge(held, "a", {"b": {"change": 2}})
    assert held == {"a": {"b": {"keep": 1, "change": 2}}}
