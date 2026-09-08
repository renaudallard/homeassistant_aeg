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

"""Tests for reading a capability tree.

Every shape here is one an appliance really sends, taken from the trees the app
ships and from a washing machine on a real account.
"""

from typing import Any

from custom_components.aeg.capability import (
    BINARY_SENSOR,
    BUTTON,
    NUMBER,
    SELECT,
    SENSOR,
    SWITCH,
    Capability,
    parse,
    platform_for,
)


def _one(payload: dict[str, Any]) -> Capability:
    found = parse(payload)
    assert len(found) == 1, found
    return found[0]


def test_reads_a_flat_field() -> None:
    field = _one({"doorState": {"access": "read", "type": "string"}})
    assert field.path == "doorState"
    assert field.name == "doorState"
    assert field.readable and not field.writable


def test_a_path_can_be_written_into_the_key() -> None:
    """The washing machine names its fields this way rather than nesting."""
    field = _one(
        {
            "applianceCareAndMaintenance0/maint1_threshold": {
                "access": "readwrite",
                "type": "int",
                "values": {},
            }
        }
    )
    assert field.path == "applianceCareAndMaintenance0/maint1_threshold"
    assert field.name == "maint1_threshold"
    assert field.values == ()


def test_walks_into_properties() -> None:
    field = _one(
        {
            "applianceInfo": {
                "type": "object",
                "properties": {"model": {"access": "read", "type": "string"}},
            }
        }
    )
    assert field.path == "applianceInfo/model"


def test_walks_into_a_bare_grouping() -> None:
    """The oven writes networkInterface with its fields directly inside."""
    fields = parse(
        {
            "networkInterface": {
                "linkQualityIndicator": {"access": "read", "type": "string"},
                "swVersion": {"access": "read", "type": "string"},
            }
        }
    )
    assert sorted(f.path for f in fields) == [
        "networkInterface/linkQualityIndicator",
        "networkInterface/swVersion",
    ]


def test_commands_become_buttons() -> None:
    """executeCommand is write only with a fixed set of values."""
    field = _one(
        {
            "executeCommand": {
                "access": "write",
                "type": "string",
                "values": {"OFF": {}, "ON": {}, "START": {}, "STOPRESET": {}},
            }
        }
    )
    assert platform_for(field) == BUTTON
    assert set(field.values) == {"OFF", "ON", "START", "STOPRESET"}


def test_a_choice_is_a_select_when_it_can_be_set() -> None:
    node = {"access": "readwrite", "type": "string", "values": {"A": {}, "B": {}}}
    assert platform_for(_one({"program": node})) == SELECT
    node["access"] = "read"
    assert platform_for(_one({"program": node})) == SENSOR


def test_a_flag_is_a_switch_when_it_can_be_set() -> None:
    node = {"access": "readwrite", "type": "boolean"}
    assert platform_for(_one({"uiLockMode": node})) == SWITCH
    node["access"] = "read"
    assert platform_for(_one({"uiLockMode": node})) == BINARY_SENSOR


def test_a_number_needs_a_range_to_be_settable() -> None:
    """Without bounds there is nothing to offer, so it stays a reading."""
    with_range = _one(
        {
            "targetTemperatureC": {
                "access": "readwrite",
                "type": "temperature",
                "min": 30.0,
                "max": 230.0,
                "step": 5.0,
            }
        }
    )
    assert platform_for(with_range) == NUMBER
    assert (with_range.minimum, with_range.maximum, with_range.step) == (
        30.0,
        230.0,
        5.0,
    )
    without = _one({"targetTemperatureC": {"access": "readwrite", "type": "number"}})
    assert platform_for(without) == SENSOR


def test_a_range_says_how_to_set_a_field_whatever_it_calls_its_type() -> None:
    """An air conditioner sets its display brightness from 0 to 100 in ones.

    It types that field as a string, and reading the type rather than the
    range made a field the appliance takes settings on into a reading nobody
    could set.
    """
    worded = _one(
        {
            "displayLight": {
                "access": "readwrite",
                "type": "string",
                "min": 0,
                "max": 100,
                "step": 1,
            }
        }
    )
    assert platform_for(worded) == NUMBER
    assert (worded.minimum, worded.maximum, worded.step) == (0.0, 100.0, 1.0)


def test_readings_stay_readings() -> None:
    assert platform_for(
        _one({"runningTime": {"access": "read", "type": "number"}})
    ) == (SENSOR)


def test_what_is_wrong_is_a_problem_not_a_reading() -> None:
    """Alerts are a list of codes, empty when nothing is wrong."""
    for kind in ("alert", "alerts"):
        field = _one({"alerts": {"access": "read", "type": kind}})
        assert platform_for(field) == BINARY_SENSOR


def test_a_field_holding_a_structure_is_not_a_reading() -> None:
    """An air purifier carries a second list of alerts and types it as one.

    A list cannot be shown as a state, so an entity on it would have sat
    unknown for as long as the appliance was there. The alerts it types as
    alerts are the ones that say anything, and it has those too.
    """
    listed = _one({"airPurifier": {"alerts": {"access": "read", "type": "array"}}})
    assert listed.path == "airPurifier/alerts"
    assert platform_for(listed) is None


def test_nothing_is_made_of_what_cannot_change_or_is_not_there() -> None:
    constant = _one(
        {"model": {"access": "constant", "type": "string", "value": "EWX1493A"}}
    )
    assert platform_for(constant) is None

    disabled = _one(
        {"startTime": {"access": "readwrite", "type": "int", "disabled": True}}
    )
    assert platform_for(disabled) is None

    grouping = _one({"userSelections": {"access": "readwrite", "type": "container"}})
    assert platform_for(grouping) is None
