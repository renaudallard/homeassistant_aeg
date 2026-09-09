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


"""What a reading is, where the appliance only says what it is called.

An appliance says a field holds a number and gives it a name, and nothing at
all about what the number means. Home Assistant wants to know: a device class
is what puts a reading beside its own kind, converts it for somebody working
in other units, and lets it be graphed and kept as history.

This guesses from the name, the way the icons do, but being wrong costs more
here. A wrong icon is a wrong picture; a wrong unit is a wrong reading, and
one Home Assistant will convert into a second wrong reading. So the table is
short on purpose, and holds only what these appliances measure in units that
nobody varies. Anything measured in units of an appliance's own choosing is
better left as the plain number it reports.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
)

from .capability import NUMERIC, Capability


@dataclass(frozen=True)
class Measure:
    """What a reading is, and what it is in."""

    device_class: SensorDeviceClass
    unit: str


# Matched against the field's own name with the separators taken out and
# lowercased. The first that fits wins, so the particular comes before the
# general: the letters of pm1 start both of the others.
LOOKS_LIKE: tuple[tuple[str, Measure], ...] = (
    (
        "pm25",
        Measure(SensorDeviceClass.PM25, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ),
    (
        "pm10",
        Measure(SensorDeviceClass.PM10, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ),
    (
        "pm1",
        Measure(SensorDeviceClass.PM1, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    ),
    ("co2", Measure(SensorDeviceClass.CO2, CONCENTRATION_PARTS_PER_MILLION)),
    ("humidity", Measure(SensorDeviceClass.HUMIDITY, PERCENTAGE)),
)


def _plain(capability: Capability) -> str:
    return capability.name.replace("_", "").lower()


def _is_a_quantity(capability: Capability) -> bool:
    """Whether a field holds a number rather than a word.

    A field that lists what it can say holds one of those words, and a word is
    not a quantity however the field is named.
    """
    return capability.kind in NUMERIC and not capability.values


def measure_for(capability: Capability) -> Measure | None:
    """What a field measures, where its name says so plainly."""
    if not _is_a_quantity(capability):
        return None
    plain = _plain(capability)
    for fragment, measure in LOOKS_LIKE:
        if fragment in plain:
            return measure
    return None


def counts_up(capability: Capability) -> bool:
    """Whether a number only ever grows, so its history is worth adding up.

    A cycle counter is the one field on these appliances that plainly does,
    and it says so in its name. Everything else that grows does it by counting
    something a cycle undoes.
    """
    if not _is_a_quantity(capability):
        return False
    plain = _plain(capability)
    return plain.endswith(("count", "counter"))
