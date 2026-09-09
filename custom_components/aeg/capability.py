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
from dataclasses import dataclass, field
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

# What an appliance calls the field saying what it is doing, and the word it
# uses for actually doing it.
STATE = "applianceState"
RUNNING = "RUNNING"

# An appliance reports its problems as a list of codes, empty when it is happy.
# Some models name the type in the singular and some in the plural.
ALERTS = frozenset({"alert", "alerts"})

# Types that hold no reading of their own. A group holds other nodes, and its
# fields appear beside it with the group written into the key, as
# "userSelections/rinse". A list holds a structure, and there is nothing an
# entity can show for one: an air purifier carries a second list of alerts
# typed this way, beside the one it types as alerts.
STRUCTURED = frozenset({"array", "careMaintenance", "complex", "container", "object"})

# Commands that undo the appliance rather than work it. One of them takes the
# appliance off the account, another uninstalls the network unit's firmware,
# and there is no getting either back from Home Assistant. A tree describes
# them the way it describes START and PAUSE, so nothing about their shape tells
# them apart and they are the one thing here refused by name.
#
# The vendor app does not offer them either. They belong to pairing an
# appliance and to a service engineer, which is not what this is for.
UNDOING = frozenset(
    {
        "networkInterface/command",
        "networkInterface/startUpCommand",
    }
)

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
    disabled: bool = False
    triggers: tuple[Any, ...] = ()
    # What each value of this field says the rest of the appliance will
    # accept, by the path of the field each change is about.
    offers: dict[str, dict[str, Any]] = field(default_factory=dict)

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


def number(value: Any) -> float | None:
    """A figure, if that is what it is. A flag is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# What a change to another field can say. It carries these whether it arrives
# on a trigger or under a value. Naming all of them is what tells a change
# from a group of them, so one writing only a range is read as the change it
# is rather than walked into as though it held fields of its own.
CHANGES = frozenset(
    {"access", "values", "disabled", "default", "range", "type", "min", "max", "step"}
)


def _changes(node: Mapping[str, Any], prefix: str, into: dict[str, Any]) -> None:
    """Flatten what one value says into the path of each field and its change."""
    for key, child in node.items():
        # A value's own "disabled" says the value is not on offer, which is
        # about the value rather than about another field.
        if not isinstance(child, Mapping):
            continue
        path = f"{prefix}/{key}" if prefix else str(key)
        if not child or set(child) & CHANGES:
            into[path] = dict(child)
        else:
            _changes(child, path, into)


def _offers(node: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """What each value of a field says the rest of the appliance will accept.

    Picking a value can change what other fields take, and an appliance says
    so under the value itself rather than as a trigger: a washing machine
    fixes the temperature of its eco programme that way, and offers six spin
    speeds on one programme where it offers three on another.

    Two spellings turn up. A washing machine and an oven write the changes
    straight into the value, each keyed by the full path of the field it is
    about. An air conditioner, an air purifier and a robot vacuum wrap them in
    an "actions" object and nest the path instead. Both end up as the same
    paths, and both mean what a trigger firing on that value would mean.
    """
    values = node.get("values")
    if not isinstance(values, Mapping):
        return {}
    offers: dict[str, dict[str, Any]] = {}
    for name, member in values.items():
        if not isinstance(member, Mapping):
            continue
        actions = member.get("actions")
        found: dict[str, Any] = {}
        _changes(actions if isinstance(actions, Mapping) else member, "", found)
        if found:
            offers[str(name)] = found
    return offers


def _on_offer(node: Mapping[str, Any]) -> tuple[str, ...]:
    """The values of a field, less the ones it has set aside.

    An appliance marks a value it will not take the way it marks a field it
    does not have. A washing machine keeps a hidden service programme in the
    list that way, and its spin speeds carry a DISABLED that is not a speed;
    an air conditioner sets aside two of the modes it describes. Offering one
    of those is offering something the appliance has said is not there.
    """
    values = node.get("values")
    if not isinstance(values, Mapping):
        return ()
    return tuple(
        str(name)
        for name, member in values.items()
        if not (isinstance(member, Mapping) and member.get("disabled") is True)
    )


def _capability(path: str, node: Mapping[str, Any]) -> Capability:
    return Capability(
        path=path,
        access=str(node.get("access", "read")),
        kind=str(node.get("type", "")),
        values=_on_offer(node),
        minimum=number(node.get("min")),
        maximum=number(node.get("max")),
        step=number(node.get("step")),
        disabled=bool(node.get("disabled", False)),
        triggers=tuple(node.get("triggers") or ()),
        offers=_offers(node),
    )


def _numbered(node: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """The members of a group that numbers them rather than naming them.

    An air purifier writes its filters as members of the group, with the
    fields of each under it. An air conditioner writes its louvres as values
    of the group instead, with the fields under those. Both mean one member
    called 0, and both come out as the same paths.

    Only a node that says it holds a structure is read this way. A field that
    holds a value has values of its own, and one of those carrying properties
    would otherwise take the field apart and leave nothing to set.
    """
    if str(node.get("type", "")) not in STRUCTURED:
        return {}
    values = node.get("values")
    if not isinstance(values, Mapping):
        return {}
    return {
        str(key): member["properties"]
        for key, member in values.items()
        if isinstance(member, Mapping) and isinstance(member.get("properties"), Mapping)
    }


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
        numbered = _numbered(node)
        if numbered:
            for member, fields in numbered.items():
                found.extend(parse(fields, f"{path}/{member}"))
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
    have, so neither is worth an entity. Nor is a field holding a structure,
    which has no single reading to show. Nor is one of the two commands that
    would undo the appliance.
    """
    if capability.disabled or capability.access == "constant":
        return None
    if capability.kind in STRUCTURED or capability.path in UNDOING:
        return None

    if capability.writable and not capability.readable:
        # Write only with a fixed set of values is a set of commands, which is
        # what executeCommand is. Without values there is nothing to press.
        return BUTTON if capability.values else None

    if capability.kind in ALERTS:
        # Something is wrong, or nothing is. The codes go alongside.
        return BINARY_SENSOR

    if capability.kind == "boolean":
        return SWITCH if capability.writable else BINARY_SENSOR

    # A range wins over a list of values. A number can carry both, where the
    # values are sentinels rather than the choice on offer: stopTime accepts
    # anything from 0 to 86400 and also -1, meaning no stop time is set.
    #
    # The range is what says how to set a field, whatever the field calls its
    # own type: an air conditioner takes a display brightness anywhere from 0
    # to 100 in steps of 1 and calls it a string.
    if capability.minimum is not None:
        return NUMBER if capability.writable else SENSOR

    if capability.values:
        return SELECT if capability.writable else SENSOR

    return SENSOR if capability.readable else None


def is_duration(capability: Capability) -> bool:
    """Whether a field holds a length of time rather than a plain number.

    An appliance names them plainly, and the ones on a washing machine that
    can be checked are in seconds: four hours of minimum finish time reads as
    14400, and a stop time runs to 86400 in steps of an hour.
    """
    return capability.kind in NUMERIC and "time" in capability.name.lower()


def counts_down(capability: Capability) -> bool:
    """Whether a duration is time left rather than time spent or time set.

    A field saying how long is left is the one thing on an appliance that is
    wrong the moment it is read, because it is a moving number and the cloud
    only mentions it now and then.
    """
    plain = capability.name.replace("_", "").lower()
    return is_duration(capability) and ("toend" in plain or "remaining" in plain)


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
