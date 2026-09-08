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

"""Tests for what an appliance will accept in the state it is in.

The tree is a real washing machine. The states are the ones it goes through.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.aeg.capability import Capability, parse
from custom_components.aeg.triggers import Override, evaluate, holds

FIXTURES = Path(__file__).parent / "fixtures"
COMMANDS = ("OFF", "ON", "START", "PAUSE", "RESUME", "STOPRESET")


@pytest.fixture
def machine() -> tuple[list[Any], dict[str, Any]]:
    capabilities = parse(json.loads((FIXTURES / "wm-capabilities.json").read_text()))
    listed = json.loads((FIXTURES / "wm-appliances.json").read_text())
    return capabilities, listed[0]["properties"]["reported"]


def _in(state: dict[str, Any], **changes: Any) -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(state))
    for key, value in changes.items():
        if key == "analogTemperature":
            copied["userSelections"]["analogTemperature"] = value
        else:
            copied[key] = value
    return copied


def _commands(capabilities: list[Any], state: dict[str, Any]) -> list[str]:
    override = evaluate(capabilities, state).get("executeCommand", Override())
    return [command for command in COMMANDS if override.allows(command)]


def test_a_machine_ready_to_start_takes_start_and_nothing_else(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    capabilities, state = machine
    ready = _in(state, applianceState="READY_TO_START", remoteControl="ENABLED")
    assert _commands(capabilities, ready) == ["START"]


def test_a_running_machine_takes_pause(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    capabilities, state = machine
    running = _in(state, applianceState="RUNNING", remoteControl="ENABLED")
    assert _commands(capabilities, running) == ["PAUSE"]


def test_a_paused_machine_can_be_resumed_or_reset(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    capabilities, state = machine
    paused = _in(state, applianceState="PAUSED", remoteControl="ENABLED")
    assert _commands(capabilities, paused) == ["RESUME", "STOPRESET"]


def test_a_command_field_made_read_only_takes_nothing() -> None:
    """An oven on a delayed start says so this way rather than by disabling."""
    capabilities = parse(
        {
            "applianceState": {
                "access": "read",
                "type": "string",
                "values": {"DELAYED_START": {}, "READY_TO_START": {}},
                "triggers": [
                    {
                        "action": {"executeCommand": {"access": "read"}},
                        "condition": {
                            "operand_1": "value",
                            "operand_2": "DELAYED_START",
                            "operator": "eq",
                        },
                    }
                ],
            },
            "executeCommand": {
                "access": "write",
                "type": "string",
                "values": {"START": {}, "STOPRESET": {}},
            },
        }
    )
    assert _commands(capabilities, {"applianceState": "DELAYED_START"}) == []
    # In any other state nothing overrides it, so it takes what it describes.
    assert "START" in _commands(capabilities, {"applianceState": "READY_TO_START"})


def test_nothing_is_accepted_while_remote_control_is_not_enabled(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    """The state the machine sits in until someone arms it at the panel."""
    capabilities, state = machine
    assert state["remoteControl"] == "NOT_SAFETY_RELEVANT_ENABLED"
    assert _commands(capabilities, state) == []


def test_settings_freeze_while_a_cycle_runs(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    capabilities, state = machine
    running = _in(state, applianceState="RUNNING", remoteControl="ENABLED")
    frozen = {
        path
        for path, override in evaluate(capabilities, running).items()
        if not override.writable
    }
    assert "waterHardness" in frozen
    assert "endOfCycleSound" in frozen


def test_a_cold_wash_will_not_take_steam(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    """Below forty degrees the machine sets steam and stain aside itself."""
    capabilities, state = machine
    cold = _in(state, remoteControl="ENABLED", analogTemperature="20_CELSIUS")
    overrides = evaluate(capabilities, cold)
    assert not overrides["userSelections/steamValue"].writable
    assert not overrides["userSelections/EWX1493A_stain"].writable

    warm = _in(state, remoteControl="ENABLED", analogTemperature="60_CELSIUS")
    warmer = evaluate(capabilities, warm)
    assert warmer["userSelections/steamValue"].writable
    assert warmer["userSelections/EWX1493A_stain"].writable


def test_the_coldest_wash_of_all_will_not_take_steam(
    machine: tuple[list[Any], dict[str, Any]],
) -> None:
    """COLD is listed after 95_CELSIUS and is colder than any of them."""
    capabilities, state = machine
    cold = _in(state, remoteControl="ENABLED", analogTemperature="COLD")
    overrides = evaluate(capabilities, cold)
    assert not overrides["userSelections/steamValue"].writable
    assert not overrides["userSelections/EWX1493A_stain"].writable


def test_a_condition_can_be_two_conditions() -> None:
    """Remote control lumps two states together with an or."""
    either = {
        "operand_1": {"operand_1": "value", "operand_2": "A", "operator": "eq"},
        "operand_2": {"operand_1": "value", "operand_2": "B", "operator": "eq"},
        "operator": "or",
    }
    assert holds(either, "A", ())
    assert holds(either, "B", ())
    assert not holds(either, "C", ())

    both = {**either, "operator": "and"}
    assert not holds(both, "A", ())


def test_values_are_ordered_by_the_number_they_spell_out() -> None:
    """The cloud lists them alphabetically, so the list order says nothing."""
    order = ("20_CELSIUS", "40_CELSIUS", "60_CELSIUS", "100_CELSIUS", "COLD")
    below = {"operand_1": "value", "operand_2": "40_CELSIUS", "operator": "lt"}
    assert holds(below, "20_CELSIUS", order)
    assert not holds(below, "60_CELSIUS", order)
    # Alphabetically a hundred sits between ten and twenty.
    assert not holds(below, "100_CELSIUS", order)


def test_a_word_with_no_number_sits_below_the_numbers() -> None:
    """COLD is listed last and is the coldest wash there is."""
    order = ("20_CELSIUS", "40_CELSIUS", "95_CELSIUS", "COLD")
    below = {"operand_1": "value", "operand_2": "40_CELSIUS", "operator": "lt"}
    at_least = {"operand_1": "value", "operand_2": "40_CELSIUS", "operator": "ge"}
    assert holds(below, "COLD", order)
    assert not holds(at_least, "COLD", order)


def test_a_spin_speed_is_read_as_a_speed() -> None:
    """Listed as 0, 1000, 1200, 1400, 400, 600, 800, which is not a scale."""
    order = ("0_RPM", "1000_RPM", "1200_RPM", "1400_RPM", "400_RPM", "800_RPM")
    below = {"operand_1": "value", "operand_2": "1000_RPM", "operator": "lt"}
    assert holds(below, "400_RPM", order)
    assert holds(below, "800_RPM", order)
    assert not holds(below, "1400_RPM", order)


def test_a_field_of_plain_words_keeps_the_order_it_came_in() -> None:
    """Nothing to order them by, so nothing is invented."""
    order = ("STEAM_MAX", "STEAM_MED", "STEAM_MIN")
    below = {"operand_1": "value", "operand_2": "STEAM_MED", "operator": "lt"}
    assert holds(below, "STEAM_MAX", order)
    assert not holds(below, "STEAM_MIN", order)


def test_default_means_the_appliance_is_not_overriding() -> None:
    assert Override(access="read").writable is False
    assert Override().writable is True
    assert Override(disabled=True).allows("START") is False
    assert Override(values=("START",)).allows("STOPRESET") is False
    assert Override(values=("START",)).allows("START") is True


def test_two_triggers_offering_values_keep_the_order_they_came_in() -> None:
    """These end up in front of someone as a list, so the order has to hold."""
    capability = Capability(
        path="fan",
        access="readwrite",
        kind="string",
        values=("LOW", "HIGH", "TURBO"),
        triggers=(
            {
                "condition": {
                    "operand_1": "value",
                    "operand_2": "LOW",
                    "operator": "eq",
                },
                "action": {"$self": {"values": {"LOW": {}, "HIGH": {}}}},
            },
            {
                "condition": {
                    "operand_1": "value",
                    "operand_2": "LOW",
                    "operator": "eq",
                },
                "action": {"$self": {"values": {"HIGH": {}, "TURBO": {}}}},
            },
        ),
    )
    override = evaluate([capability], {"fan": "LOW"})["fan"]
    assert override.values == ("LOW", "HIGH", "TURBO")


def test_an_unknown_operator_is_not_guessed_at() -> None:
    assert not holds({"operand_1": "value", "operand_2": 1, "operator": "wat"}, 1, ())
