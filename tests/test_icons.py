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
from custom_components.aeg.icons import icon_for, icon_for_command


def _field(name: str, kind: str = "string") -> Capability:
    return Capability(path=name, access="read", kind=kind)


def test_the_particular_beats_the_general() -> None:
    """A door lock is a lock, and a crease guard is not a steam setting."""
    assert icon_for(_field("doorLock")) == "mdi:lock"
    assert icon_for(_field("doorState")) == "mdi:door"
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


def test_a_name_that_says_nothing_gets_nothing() -> None:
    assert icon_for(_field("cpv")) is None
    assert icon_for(_field("EWX1493A_tcSensor")) is None


def test_a_command_is_shown_by_what_it_does() -> None:
    assert icon_for_command("START") == "mdi:play"
    assert icon_for_command("PAUSE") == "mdi:pause"
    assert icon_for_command("STOPRESET") == "mdi:stop"
    # Anything else is at least pressable.
    assert icon_for_command("DESCALE") == "mdi:gesture-tap-button"
