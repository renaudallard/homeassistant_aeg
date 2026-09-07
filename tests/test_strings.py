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

"""Tests that the config flow and its text agree.

A step or an error key with no entry in strings.json still renders, just as a
blank panel or a raw key, so nothing fails loudly when they drift apart. These
read the flow itself and check every id it uses has text behind it.
"""

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "aeg"
FLOW = COMPONENT / "config_flow.py"
STRINGS = COMPONENT / "strings.json"
ENGLISH = COMPONENT / "translations" / "en.json"


def _flow() -> ast.Module:
    return ast.parse(FLOW.read_text())


def _strings() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(STRINGS.read_text())
    return loaded


def _step_ids(tree: ast.Module) -> set[str]:
    """Every step the flow shows, whether as a form or as a menu entry."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "step_id"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                found.add(keyword.value.value)
            if keyword.arg == "menu_options" and isinstance(keyword.value, ast.List):
                found.update(
                    element.value
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
    return found


def _error_keys(tree: ast.Module) -> set[str]:
    """Every key the flow can put into the errors mapping."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Subscript)]
        if not any(
            isinstance(t.value, ast.Name) and t.value.id == "errors" for t in targets
        ):
            continue
        found.update(
            child.value
            for child in ast.walk(node.value)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        )
    return found


def test_every_step_has_text() -> None:
    steps = _strings()["config"]["step"]
    missing = sorted(_step_ids(_flow()) - set(steps))
    assert not missing, f"steps with no text: {missing}"


def test_every_error_has_text() -> None:
    errors = _strings()["config"]["error"]
    missing = sorted(_error_keys(_flow()) - set(errors))
    assert not missing, f"error keys with no text: {missing}"


def test_no_unused_text() -> None:
    """Text left behind after a step or an error key is dropped."""
    tree = _flow()
    strings = _strings()
    stale_steps = sorted(set(strings["config"]["step"]) - _step_ids(tree) - {"user"})
    stale_errors = sorted(set(strings["config"]["error"]) - _error_keys(tree))
    assert not stale_steps, f"text for steps that are gone: {stale_steps}"
    assert not stale_errors, f"text for error keys that are gone: {stale_errors}"


def test_menu_options_have_labels() -> None:
    menu = _strings()["config"]["step"]["user"]["menu_options"]
    tree = _flow()
    options = {
        element.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "menu_options" and isinstance(keyword.value, ast.List)
        for element in keyword.value.elts
        if isinstance(element, ast.Constant)
    }
    assert options == set(menu), "menu entries and their labels disagree"


def test_english_matches_strings() -> None:
    assert json.loads(ENGLISH.read_text()) == _strings()
