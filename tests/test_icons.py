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

"""Tests for choosing something to look at beside a reading.

The guess is made from the field's own name and never from the model, so these
are about the rules rather than about a washing machine.
"""

from custom_components.aeg.capability import Capability
from custom_components.aeg.icons import (
    BY_READING,
    as_read,
    icon_for,
    icon_for_command,
    icon_for_reading,
)
from custom_components.aeg.names import PLATFORMS_FOR


def _field(name: str, kind: str = "string", access: str = "read") -> Capability:
    return Capability(path=name, access=access, kind=kind)


def test_the_particular_beats_the_general() -> None:
    """A crease guard is not a steam setting, and a lid lock is a lock."""
    assert icon_for(_field("lidLock")) == "mdi:lock"
    assert icon_for(_field("EWX1493A_anticreaseWSteam")) == "mdi:iron"
    assert icon_for(_field("steamValue")) == "mdi:kettle-steam"
    assert icon_for(_field("waterHardness")) == "mdi:water-percent"
    assert icon_for(_field("waterUsage")) == "mdi:water"


def test_a_model_code_on_the_front_is_no_obstacle() -> None:
    assert icon_for(_field("EWX1493A_nightCycle")) == "mdi:weather-night"
    assert icon_for(_field("EWX1493A_wmEconomy")) == "mdi:leaf"


def test_nothing_is_guessed_where_something_better_answers() -> None:
    """A device class says more than a guess from a name."""
    assert icon_for(_field("timeToEnd", "number")) is None
    assert icon_for(_field("targetTemperatureC", "temperature")) is None
    assert icon_for(_field("alerts", "alert")) is None


def test_a_fragment_has_to_be_a_word_and_not_a_run_of_letters() -> None:
    """remoteControl carries the letters of eco across the join in the middle.

    So does totalCycleCounter, and both were being shown a leaf.
    """
    assert icon_for(_field("remoteControl")) == "mdi:remote"
    assert icon_for(_field("totalCycleCounter")) == "mdi:sync"
    # And a field that really is about it still gets the leaf.
    assert icon_for(_field("ecoLevel")) == "mdi:leaf"
    assert icon_for(_field("wmEconomy")) == "mdi:leaf"


def test_a_fragment_may_still_span_two_words() -> None:
    """A lid lock is a lock rather than a lid, and that is two words."""
    assert icon_for(_field("lidLock")) == "mdi:lock"
    assert icon_for(_field("waterHardness")) == "mdi:water-percent"
    assert icon_for(_field("uiLockState")) == "mdi:lock"


def test_a_name_that_says_nothing_gets_nothing() -> None:
    assert icon_for(_field("cpv")) is None
    assert icon_for(_field("EWX1493A_tcSensor")) is None


def test_a_command_is_shown_by_what_it_does() -> None:
    assert icon_for_command("START") == "mdi:play"
    assert icon_for_command("PAUSE") == "mdi:pause"
    assert icon_for_command("STOPRESET") == "mdi:stop"
    # Anything else is at least pressable.
    assert icon_for_command("DESCALE") == "mdi:gesture-tap-button"


def test_a_reading_is_matched_however_the_model_spells_it() -> None:
    """A washer says END_OF_CYCLE, a vacuum says endOfCycle, and both mean it."""
    assert as_read("END_OF_CYCLE") == "endofcycle"
    assert as_read("endOfCycle") == "endofcycle"
    assert as_read("RUNNING") == as_read("running") == "running"
    # Some report a flag as a word and some as a true.
    assert as_read(True) == "on"
    assert as_read(False) == "off"
    assert as_read("ON") == "on"


def test_a_door_looks_the_way_it_is() -> None:
    for state in ("OPEN", "open"):
        assert icon_for_reading("sensor", "door_state", state) == "mdi:door-open"
    assert icon_for_reading("sensor", "door_state", "CLOSED") == "mdi:door-closed"


def test_a_lock_looks_undone_when_it_is_undone() -> None:
    assert icon_for_reading("sensor", "door_lock", "ON") == "mdi:lock"
    assert icon_for_reading("sensor", "door_lock", "OFF") == "mdi:lock-open-variant"
    assert icon_for_reading("sensor", "door_lock", "LOCKING") == "mdi:lock-clock"
    # And the panel lock, whichever of its four names it goes by.
    for key in ("child_lock", "ui_lock", "ui_lock_mode", "ui_locked"):
        assert icon_for_reading("switch", key, True) == "mdi:lock"
        assert icon_for_reading("switch", key, False) == "mdi:lock-open-variant"


def test_a_remote_control_that_will_take_nothing_says_so() -> None:
    """Only ENABLED takes a command, whatever the other three names suggest.

    The appliance says so itself: the trigger on the field turns executeCommand
    off for NOT_SAFETY_RELEVANT_ENABLED and DISABLED alike, and the buttons
    that go with it are already tested against exactly that. No tree rules on
    TEMPORARY_LOCKED, so its name is all there is to go on.
    """
    for refusing in ("DISABLED", "NOT_SAFETY_RELEVANT_ENABLED", "TEMPORARY_LOCKED"):
        assert (
            icon_for_reading("sensor", "remote_control", refusing) == "mdi:remote-off"
        )
    assert icon_for_reading("sensor", "remote_control", "ENABLED") == "mdi:remote"


def test_every_state_the_models_declare_has_a_picture() -> None:
    """Gathered from all ten capability trees, so no model is left drawing the
    fallback for a state it uses every day."""
    declared = {
        ("sensor", "appliance_state"): (
            "OFF IDLE READY_TO_START DELAYED_START RUNNING PAUSED END_OF_CYCLE "
            "ALARM off running readyToStart delayedStart endOfCycle paused alarm "
            "monitoring idle"
        ),
        ("sensor", "connectivity_state"): "connected disconnected",
        ("sensor", "door_state"): "OPEN CLOSED",
        ("sensor", "door_lock"): "ON OFF LOCKING UNLOCKING",
        ("sensor", "remote_control"): (
            "ENABLED DISABLED NOT_SAFETY_RELEVANT_ENABLED TEMPORARY_LOCKED"
        ),
    }
    for (platform, key), states in declared.items():
        for state in states.split():
            assert icon_for_reading(platform, key, state), f"{key} {state}"


def test_a_state_nobody_listed_falls_back_to_the_guess() -> None:
    """A model that invents a ninth state still has something to look at."""
    assert icon_for_reading("sensor", "appliance_state", "SOMETHING_NEW") is None
    assert icon_for(_field("applianceState")) == "mdi:information-outline"


def test_a_field_it_says_nothing_about_is_drawn_by_its_name_alone() -> None:
    assert icon_for_reading("sensor", "water_hardness", "SOFT") is None
    assert icon_for_reading(None, "door_state", "OPEN") is None
    assert icon_for(_field("waterHardness")) == "mdi:water-percent"


def test_every_field_it_draws_is_one_that_turns_up_there() -> None:
    """A key nothing is named under, or on a platform it never lands on, draws
    a picture nobody will ever see."""
    for platform, key in BY_READING:
        assert key in PLATFORMS_FOR, key
        assert platform in PLATFORMS_FOR[key], (platform, key)
