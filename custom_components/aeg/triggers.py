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

"""What an appliance will accept right now.

A capability says what a field is in general. Triggers say what it is at this
moment: a washing machine takes START when it is ready to start and not while
it is running, and will not take a steam setting at all below forty degrees.

A trigger hangs off the field it watches. Its condition compares that field's
current value against something, and its action changes other fields: their
access, the values they will take, or whether they are there at all.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .capability import Capability, value_at

_LOGGER = logging.getLogger(__name__)

ORDERED = ("lt", "le", "gt", "ge")

# The number a value spells out, as in the 20 of 20_CELSIUS or the 1400 of
# 1400_RPM.
NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class Override:
    """What the triggers currently say about one field."""

    access: str | None = None
    values: tuple[str, ...] | None = None
    disabled: bool | None = None

    def allows(self, command: str) -> bool:
        """Whether a command is one this field will take right now."""
        if self.disabled:
            return False
        return self.values is None or command in self.values

    @property
    def writable(self) -> bool:
        if self.disabled:
            return False
        return self.access is None or "write" in self.access


def _measure(value: str) -> float | None:
    """The number a word spells out, if it spells one out at all."""
    found = NUMBER.search(value)
    return float(found.group()) if found else None


def _scale(order: Sequence[str]) -> tuple[str, ...]:
    """Put a field's values in the order it means them, not the one they came in.

    The cloud lists them alphabetically. A spin speed arrives as 0, 1000, 1200,
    1400, 400, 600, 800 and a temperature ends on COLD, so where a value sits
    in the list says nothing about which of two is the larger.

    A value that spells out a number is ordered by that number. One that does
    not keeps the order it came in and sits below the rest, which is where the
    words on these fields belong: COLD is under every temperature and DISABLED
    under every spin speed. A field whose values are all words is left as it
    came, there being nothing to order it by.
    """
    measured = [(value, _measure(value)) for value in order]
    numbered = sorted(
        (number, value) for value, number in measured if number is not None
    )
    return (
        *(value for value, number in measured if number is None),
        *(value for _, value in numbered),
    )


def _rank(value: Any, order: Sequence[str]) -> float | None:
    """Where a value sits on a scale, so that two of them can be compared."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value in order:
        return float(order.index(value))
    return None


def _compare(operator: str, left: Any, right: Any, order: Sequence[str]) -> bool:
    if operator == "eq":
        return bool(left == right)
    if operator == "ne":
        return bool(left != right)
    if operator in ORDERED:
        scale = _scale(order)
        first, second = _rank(left, scale), _rank(right, scale)
        if first is None or second is None:
            return False
        if operator == "lt":
            return first < second
        if operator == "le":
            return first <= second
        if operator == "gt":
            return first > second
        return first >= second
    _LOGGER.debug("unknown trigger operator %s", operator)
    return False


def holds(condition: Any, value: Any, order: Sequence[str]) -> bool:
    """Whether a condition is true of a field's current value."""
    if not isinstance(condition, Mapping):
        return False
    operator = str(condition.get("operator", ""))
    left = condition.get("operand_1")
    right = condition.get("operand_2")
    if operator in ("and", "or"):
        first = holds(left, value, order)
        second = holds(right, value, order)
        return (first and second) if operator == "and" else (first or second)
    # A leaf condition reads the field the trigger hangs off.
    return _compare(operator, value if left == "value" else left, right, order)


def _fold(into: dict[str, Override], path: str, change: Mapping[str, Any]) -> None:
    held = into.get(path, Override())
    values = held.values
    if isinstance(change.get("values"), Mapping):
        # Two triggers can each allow a command, so take both.
        offered = tuple(change["values"])
        values = offered if values is None else tuple({*values, *offered})
    disabled = held.disabled
    if isinstance(change.get("disabled"), bool):
        # Anything saying a field is gone wins over anything saying it is not.
        disabled = bool(change["disabled"]) or bool(disabled)
    access = change.get("access", held.access)
    if access == "default":
        # The appliance saying "default" means it is not overriding at all.
        access = None
    into[path] = Override(
        access=str(access) if access is not None else None,
        values=values,
        disabled=disabled,
    )


def evaluate(
    capabilities: Sequence[Capability], reported: Mapping[str, Any]
) -> dict[str, Override]:
    """Work out what every field will accept, given the state right now."""
    found: dict[str, Override] = {}
    for capability in capabilities:
        if not capability.triggers:
            continue
        value = value_at(reported, capability.path)
        for trigger in capability.triggers:
            if not isinstance(trigger, Mapping):
                continue
            if not holds(trigger.get("condition"), value, capability.values):
                continue
            action = trigger.get("action")
            if not isinstance(action, Mapping):
                continue
            for target, change in action.items():
                if isinstance(change, Mapping):
                    path = capability.path if target == "$self" else str(target)
                    _fold(found, path, change)
    return found
