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

"""Tests for reading a scale of values as the numbers it is.

A field can name the first few steps and number the rest. The washing machine
here sets water hardness to SOFT, MEDIUM, HARD and then STEP_4 up to STEP_7,
which the dex confirms is one scale: it carries STEP_1, STEP_2 and STEP_3 too,
for models that number all seven.
"""

from custom_components.aeg.select import numbering


def test_a_scale_that_names_its_first_steps_is_still_a_scale() -> None:
    scale = numbering(
        ("SOFT", "MEDIUM", "HARD", "STEP_4", "STEP_5", "STEP_6", "STEP_7")
    )
    assert scale == {
        "SOFT": "1",
        "MEDIUM": "2",
        "HARD": "3",
        "STEP_4": "4",
        "STEP_5": "5",
        "STEP_6": "6",
        "STEP_7": "7",
    }


def test_a_scale_that_numbers_every_step() -> None:
    assert numbering(("STEP_1", "STEP_2", "STEP_3")) == {
        "STEP_1": "1",
        "STEP_2": "2",
        "STEP_3": "3",
    }


def test_numbers_that_do_not_land_on_their_own_place_count_something_else() -> None:
    """The check that stops a list of names being numbered off the back of it."""
    assert numbering(("MODE_3", "MODE_9")) == {}
    assert numbering(("STEP_4", "STEP_5", "SOFT", "MEDIUM")) == {}


def test_a_choice_that_is_not_a_scale_is_left_alone() -> None:
    assert numbering(("EXTRA_RINSE_OFF", "EXTRA_RINSE_ON")) == {}
    assert numbering(("DISABLED", "WASH_ONLY", "WASH_AND_RINSE")) == {}


def test_a_number_in_front_is_not_a_place_in_a_scale() -> None:
    """Spin speeds and temperatures lead with their number and mean it."""
    assert numbering(("1000_RPM", "1200_RPM", "1400_RPM")) == {}
    assert numbering(("30_CELSIUS", "40_CELSIUS", "60_CELSIUS")) == {}


def test_one_numbered_value_is_not_enough_to_go_on() -> None:
    assert numbering(("MODE_1", "SOMETHING", "ANOTHER")) == {}
