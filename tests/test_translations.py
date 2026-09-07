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

"""Tests that the translations keep step with the English.

A language file that has drifted from strings.json shows a raw key or an empty
name in front of someone, and nothing fails to say so. These read the files and
check they still line up.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "aeg"
WORDS = Path(__file__).resolve().parent.parent / "tools" / "translations.json"
LANGUAGES = ("da", "de", "en", "es", "fr", "it", "nl", "pl", "sv")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _load(name: str) -> Any:
    return json.loads((COMPONENT / "translations" / f"{name}.json").read_text())


def _english() -> Any:
    return json.loads((COMPONENT / "strings.json").read_text())


def _paths(node: Any, at: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        found: dict[str, str] = {}
        for key, value in node.items():
            found |= _paths(value, f"{at}.{key}")
        return found
    return {at: node}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_language_says_everything_the_english_does(language: str) -> None:
    assert set(_paths(_load(language))) == set(_paths(_english()))


@pytest.mark.parametrize("language", LANGUAGES)
def test_nothing_is_left_empty(language: str) -> None:
    empty = [
        where for where, said in _paths(_load(language)).items() if not said.strip()
    ]
    assert not empty, f"{language} says nothing at {empty}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_what_gets_filled_in_survives_translation(language: str) -> None:
    """A code goes to an address, and the address has to still be in the words."""
    english = _paths(_english())
    for where, said in _paths(_load(language)).items():
        assert set(PLACEHOLDER.findall(said)) == set(
            PLACEHOLDER.findall(english[where])
        ), f"{language} lost or gained a placeholder at {where}"


def test_every_string_has_words_in_every_language() -> None:
    says = json.loads(WORDS.read_text())
    spoken = [language for language in LANGUAGES if language != "en"]
    for english in set(_paths(_english()).values()):
        assert english in says, f"nothing written for {english!r}"
        assert set(says[english]) == set(spoken), f"{english!r} is missing a language"
