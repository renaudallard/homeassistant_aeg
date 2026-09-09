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


"""Tests for what a reading is taken to be.

The table guesses from a field's name, and a wrong guess here is a wrong
reading rather than a wrong picture, so what it leaves alone matters as much
as what it claims.
"""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER, PERCENTAGE

from custom_components.aeg.capability import Capability, parse
from custom_components.aeg.icons import icon_for
from custom_components.aeg.measures import counts_up, measure_for


def _one(payload: dict[str, Any]) -> Capability:
    found = parse(payload)
    assert len(found) == 1, found
    return found[0]


def test_a_particulate_is_read_in_micrograms() -> None:
    for name, expected in (
        ("PM1", SensorDeviceClass.PM1),
        ("PM2_5", SensorDeviceClass.PM25),
        ("PM10", SensorDeviceClass.PM10),
    ):
        measure = measure_for(_one({name: {"access": "read", "type": "number"}}))
        assert measure is not None, name
        assert measure.device_class == expected
        assert measure.unit == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER


def test_humidity_is_a_percentage() -> None:
    measure = measure_for(_one({"humidity": {"access": "read", "type": "number"}}))
    assert measure is not None
    assert measure.device_class == SensorDeviceClass.HUMIDITY
    assert measure.unit == PERCENTAGE


def test_a_field_that_holds_a_word_is_no_quantity() -> None:
    """A humidity setting of LOW is not a percentage of anything."""
    field = _one(
        {
            "humidityTarget": {
                "access": "read",
                "type": "string",
                "values": {"HIGH": {}, "LOW": {}},
            }
        }
    )
    assert measure_for(field) is None


def test_a_number_that_lists_its_values_is_no_quantity_either() -> None:
    field = _one(
        {
            "humidityLevel": {
                "access": "read",
                "type": "number",
                "values": {"1": {}, "2": {}},
            }
        }
    )
    assert measure_for(field) is None


def test_it_claims_nothing_it_was_not_asked_about() -> None:
    """Weight and water are measured in units these appliances pick for themselves."""
    for name in (
        "measuredLoadWeight",
        "waterUsage",
        "tvoc",
        "displayBrightness",
        "applianceState",
    ):
        field = _one({name: {"access": "read", "type": "number"}})
        assert measure_for(field) is None, name


def test_a_counter_is_worth_adding_up() -> None:
    for name in ("totalCycleCounter", "totalWashCyclesCount"):
        assert counts_up(_one({name: {"access": "read", "type": "number"}})), name


def test_a_reading_that_goes_up_and_down_is_not() -> None:
    for name in ("timeToEnd", "ambientTemperatureC", "waterHardness"):
        assert not counts_up(_one({name: {"access": "read", "type": "number"}})), name


def test_a_field_that_says_what_it_is_gets_no_guessed_icon() -> None:
    """Home Assistant draws a device class better than this table can."""
    assert icon_for(_one({"humidity": {"access": "read", "type": "number"}})) is None
    # And one that says nothing still gets the guess.
    assert icon_for(_one({"doorState": {"access": "read", "type": "string"}}))
