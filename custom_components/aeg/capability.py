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

"""The appliance capability tree, and what it becomes in Home Assistant.

Every appliance describes itself. A capability says what a field is called,
whether it can be read or written, what type it holds and, where it applies,
which values or what range it accepts. That is enough to decide what kind of
entity it should be, so nothing here is specific to a model of washing machine
or oven.

Two shapes turn up in the same tree. Most nodes are flat, with the path written
into the key as "userSelections/analogTemperature". Some are nested under a
"properties" object instead. Both are walked here and end up as the same paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# What a node becomes. These are Home Assistant platform names, kept as plain
# strings so this module does not need Home Assistant to be tested.
SENSOR = "sensor"
BINARY_SENSOR = "binary_sensor"
SWITCH = "switch"
SELECT = "select"
NUMBER = "number"
BUTTON = "button"

# Types that hold a number rather than a word.
NUMERIC = frozenset({"number", "int", "temperature"})

# Types that group other nodes and hold nothing themselves. Their fields appear
# beside them with the group written into the key, as "userSelections/rinse".
GROUPING = frozenset({"container", "object", "careMaintenance", "complex"})

# Groups that describe the machine's own housekeeping rather than the wash.
# Their fields are worth having but not worth showing by default.
HOUSEKEEPING = (
    "applianceCareAndMaintenance",
    "cycleMemory",
    "dwywWashData",
    "fCMiscellaneousState",
    "miscellaneous",
    "networkInterface",
)


@dataclass(frozen=True)
class Capability:
    """One writable or readable field of an appliance."""

    path: str
    access: str
    kind: str
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    default: Any = None
    disabled: bool = False

    @property
    def readable(self) -> bool:
        return "read" in self.access

    @property
    def writable(self) -> bool:
        return "write" in self.access

    @property
    def name(self) -> str:
        """The last segment, which is what the field is actually called."""
        return self.path.rsplit("/", 1)[-1]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _capability(path: str, node: Mapping[str, Any]) -> Capability:
    values = node.get("values")
    return Capability(
        path=path,
        access=str(node.get("access", "read")),
        kind=str(node.get("type", "")),
        values=tuple(values) if isinstance(values, dict) and values else (),
        minimum=_number(node.get("min")),
        maximum=_number(node.get("max")),
        step=_number(node.get("step")),
        default=node.get("default"),
        disabled=bool(node.get("disabled", False)),
    )


def parse(payload: Mapping[str, Any], prefix: str = "") -> list[Capability]:
    """Flatten a capability tree into the fields it describes."""
    found: list[Capability] = []
    for key, node in payload.items():
        if not isinstance(node, dict):
            continue
        path = f"{prefix}/{key}" if prefix else str(key)
        properties = node.get("properties")
        if isinstance(properties, dict):
            # A grouping node holds nothing itself, only the fields under it.
            found.extend(parse(properties, path))
            continue
        if "access" in node or "type" in node:
            found.append(_capability(path, node))
            continue
        # A bare object that says nothing about itself is a grouping too. The
        # oven writes networkInterface that way, with its fields directly
        # inside and no properties around them.
        found.extend(parse(node, path))
    return found


def platform_for(capability: Capability) -> str | None:
    """Which kind of entity a field should become, or none at all.

    A constant never changes and a disabled field is one this model does not
    have, so neither is worth an entity. Groupings hold nothing themselves.
    """
    if capability.disabled or capability.access == "constant":
        return None
    if capability.kind in GROUPING:
        return None

    if capability.writable and not capability.readable:
        # Write only with a fixed set of values is a set of commands, which is
        # what executeCommand is. Without values there is nothing to press.
        return BUTTON if capability.values else None

    if capability.kind == "boolean":
        return SWITCH if capability.writable else BINARY_SENSOR

    # A range wins over a list of values. A number can carry both, where the
    # values are sentinels rather than the choice on offer: stopTime accepts
    # anything from 0 to 86400 and also -1, meaning no stop time is set.
    if capability.kind in NUMERIC and capability.minimum is not None:
        return NUMBER if capability.writable else SENSOR

    if capability.values:
        return SELECT if capability.writable else SENSOR

    return SENSOR if capability.readable else None


def is_housekeeping(capability: Capability) -> bool:
    """Whether a field is the machine talking to itself.

    Maintenance counters, stored cycles and the network stack are all readable
    and worth keeping, but nobody wants forty of them in front of the wash.
    """
    return capability.path.startswith(HOUSEKEEPING)


def value_at(reported: Mapping[str, Any], path: str) -> Any:
    """Follow a capability path into the state an appliance reports.

    Capabilities write the path into the key, as "userSelections/rinse", while
    the reported state nests the same thing. Missing is not an error: a field
    an appliance describes is not always one it currently reports.
    """
    current: Any = reported
    for segment in path.split("/"):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current
