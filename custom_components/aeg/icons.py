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

"""Something to look at beside each reading.

An appliance says what its fields are called and nothing about what they mean,
so this is the one place that guesses. It guesses from the name alone and never
from the model, so an appliance nobody here has gets the same treatment as the
one this was written against, and getting it wrong costs a wrong picture rather
than a wrong reading.

Nothing here is asked about a field that already carries a device class, since
Home Assistant has a better answer for those than a guess. Nor about a field
whose icon should move with its reading, which is icons.json's job.
"""

from __future__ import annotations

import re

from .capability import ALERTS, Capability, is_duration, platform_for
from .measures import measure_for
from .names import key_for

# Where one of a field's words ends and the next begins, at an underscore or
# at the capital of a name written in camel case.
BETWEEN_WORDS = re.compile(r"_+|(?<=[a-z0-9])(?=[A-Z])")


def _words(name: str) -> tuple[str, set[int]]:
    """A field's name run together, and where each of its words begins.

    A fragment below has to line up with the start of a word rather than turn
    up anywhere in the letters. remoteControl holds the letters of eco across
    the join between its two words and is not about ecology; so does
    totalCycleCounter, and both were being shown a leaf.
    """
    plain = ""
    starts = set()
    for word in BETWEEN_WORDS.split(name):
        if not word:
            continue
        starts.add(len(plain))
        plain += word.lower()
    return plain, starts


# Matched against the field's own name, a word at a time and lowercased. The
# first that fits wins, so the particular comes before the general: a door lock
# is a lock rather than a door, and water hardness is neither a temperature nor
# a tap. A fragment can span two words, as doorlock does.
LOOKS_LIKE: tuple[tuple[str, str], ...] = (
    ("doorlock", "mdi:lock"),
    ("door", "mdi:door"),
    ("uilock", "mdi:lock"),
    ("childlock", "mdi:lock"),
    ("lock", "mdi:lock"),
    ("program", "mdi:playlist-play"),
    ("spinspeed", "mdi:rotate-right"),
    ("spin", "mdi:rotate-right"),
    ("waterhardness", "mdi:water-percent"),
    ("softener", "mdi:water-percent"),
    ("hardness", "mdi:water-percent"),
    ("rinse", "mdi:water-sync"),
    # Before steam, since a crease guard that runs without steam is still
    # about creases.
    ("anticrease", "mdi:iron"),
    ("steam", "mdi:kettle-steam"),
    ("water", "mdi:water"),
    ("humidity", "mdi:water-percent"),
    ("temperature", "mdi:thermometer"),
    ("economy", "mdi:leaf"),
    ("eco", "mdi:leaf"),
    ("night", "mdi:weather-night"),
    ("stain", "mdi:spray-bottle"),
    ("iron", "mdi:iron"),
    ("dry", "mdi:tumble-dryer"),
    ("prewash", "mdi:washing-machine"),
    ("wash", "mdi:washing-machine"),
    ("cycle", "mdi:sync"),
    ("phase", "mdi:sync"),
    ("filter", "mdi:air-filter"),
    ("fan", "mdi:fan"),
    ("sound", "mdi:volume-high"),
    ("light", "mdi:lightbulb"),
    ("display", "mdi:monitor"),
    ("notification", "mdi:bell"),
    ("remote", "mdi:remote"),
    ("network", "mdi:wifi"),
    ("wifi", "mdi:wifi"),
    ("link", "mdi:wifi"),
    ("version", "mdi:chip"),
    ("firmware", "mdi:chip"),
    ("count", "mdi:counter"),
    ("weight", "mdi:weight-kilogram"),
    ("load", "mdi:weight-kilogram"),
    ("memory", "mdi:content-save"),
    ("language", "mdi:translate"),
    ("maint", "mdi:wrench"),
    ("mode", "mdi:tune"),
    ("level", "mdi:format-list-numbered"),
    ("state", "mdi:information-outline"),
)

# Fields whose picture says something the name cannot: which way the door is,
# whether the lock is on, what the machine is up to. Those are drawn in
# icons.json, which Home Assistant reads a picture out of by the state, and a
# guess made here would be an icon of its own and win over it. The test holds
# this and the file to each other, so neither can drift.
BY_STATE: frozenset[tuple[str, str]] = frozenset(
    {
        ("sensor", "appliance_state"),
        ("sensor", "connectivity_state"),
        ("sensor", "door_lock"),
        ("sensor", "door_state"),
        ("sensor", "remote_control"),
        ("switch", "child_lock"),
        ("switch", "ui_lock"),
        ("switch", "ui_lock_mode"),
        ("switch", "ui_locked"),
    }
)

# A command is better shown by what it does than by what it belongs to.
COMMANDS: dict[str, str] = {
    "OFF": "mdi:power-off",
    "ON": "mdi:power-on",
    "START": "mdi:play",
    "RESUME": "mdi:play",
    "PAUSE": "mdi:pause",
    "STOPRESET": "mdi:stop",
    "STOP": "mdi:stop",
}


def icon_for(capability: Capability) -> str | None:
    """A picture for a field, or none where something better already answers."""
    if is_duration(capability) or capability.kind in ALERTS:
        return None
    if capability.kind == "temperature" or measure_for(capability) is not None:
        return None
    if (platform_for(capability), key_for(capability.name)) in BY_STATE:
        return None
    plain, starts = _words(capability.name)
    for fragment, icon in LOOKS_LIKE:
        at = plain.find(fragment)
        while at != -1:
            if at in starts:
                return icon
            at = plain.find(fragment, at + 1)
    return None


def icon_for_command(command: str) -> str:
    """A picture for one command, falling back to something pressable."""
    return COMMANDS.get(command.upper(), "mdi:gesture-tap-button")
