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

import json
import re
from pathlib import Path
from typing import Any

from custom_components.aeg.capability import Capability
from custom_components.aeg.icons import BY_STATE, icon_for, icon_for_command
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

    So does totalCycleCounter, and both were being shown a leaf. The remote
    control is drawn by its state now and answers nothing here, so the counter
    is what is left to show the rule: it falls through to the cycle it is
    counting rather than stopping at the letters in the middle of it.
    """
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


ICONS = Path(__file__).parent.parent / "custom_components" / "aeg" / "icons.json"


def _drawn_by_state() -> dict[tuple[str, str], dict[str, Any]]:
    """Every field icons.json draws, by the platform and key it draws it on."""
    entity = json.loads(ICONS.read_text())["entity"]
    return {
        (platform, key): body
        for platform, keys in entity.items()
        for key, body in keys.items()
    }


def test_the_file_and_the_list_of_what_is_in_it_agree() -> None:
    """A field in one and not the other loses its icon or keeps a wrong one."""
    assert set(_drawn_by_state()) == set(BY_STATE)


def test_every_field_it_draws_is_one_that_turns_up_there() -> None:
    """A key nothing is named under, or on a platform it never lands on, draws
    nothing at all."""
    for platform, key in _drawn_by_state():
        assert key in PLATFORMS_FOR, key
        assert platform in PLATFORMS_FOR[key], (platform, key)


# What hassfest will take as a key, which is the check that failed in CI
# rather than here the first time this file was written.
A_KEY = re.compile(r"^(?!.*[-_]$)[a-z0-9][a-z0-9-_]*$")


def test_every_key_in_it_is_one_home_assistant_will_take() -> None:
    """Lower case only, which these appliances are not.

    A door says OPEN and a state says END_OF_CYCLE, and hassfest refuses both,
    so a field that shouts cannot be drawn by its state at all. Catching that
    here is the difference between a failing test and a failing release.
    """
    entity = json.loads(ICONS.read_text())["entity"]
    for platform, keys in entity.items():
        assert A_KEY.match(platform), platform
        for key, body in keys.items():
            assert A_KEY.match(key), key
            for state in body.get("state", {}):
                assert A_KEY.match(state), f"{platform}.{key}.{state}"


def test_each_of_them_has_a_picture_to_fall_back_on() -> None:
    """A state nobody predicted still has to look like something."""
    for (platform, key), body in _drawn_by_state().items():
        assert body.get("default"), (platform, key)
        assert body.get("state"), (platform, key)


def test_nothing_guesses_over_a_field_drawn_by_its_state() -> None:
    """An icon set here would win over the one Home Assistant reads by state.

    A panel lock is drawn by its state where it is a switch, which is where
    icons.json claims it, and guessed at where it is only reported.
    """
    assert icon_for(_field("uiLockMode", "boolean", "readwrite")) is None
    assert icon_for(_field("childLock", "boolean", "readwrite")) is None
    assert icon_for(_field("uiLockMode", "boolean")) == "mdi:lock"


def test_a_field_that_shouts_keeps_its_guess() -> None:
    """Home Assistant will not key an icon on OPEN, so the door is guessed at."""
    assert icon_for(_field("doorState")) == "mdi:door"
    assert icon_for(_field("doorLock")) == "mdi:lock"
    assert icon_for(_field("applianceState")) == "mdi:information-outline"
    assert icon_for(_field("remoteControl")) == "mdi:remote"


def test_a_field_it_does_not_draw_still_gets_its_guess() -> None:
    assert icon_for(_field("waterHardness")) == "mdi:water-percent"
    assert icon_for(_field("cyclePhase")) == "mdi:sync"
