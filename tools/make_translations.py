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

"""Write the translations out, from one file of what everything says.

Every language file has the same shape as strings.json, so translating is a
matter of the words rather than the structure. The words live in
tools/translations.json, keyed by the English, because that is data rather than
code and a translator should not have to read Python to work on it.

    python tools/make_translations.py

Run it after changing strings.json, which tools/make_names.py writes the entity
part of. It says which strings it had no words for, and leaves those in
English rather than leaving them out.
"""

from __future__ import annotations

import json
from pathlib import Path

COMPONENT = Path("custom_components/aeg")
WORDS = Path("tools/translations.json")
LANGUAGES = ("da", "de", "es", "fr", "it", "nl", "pl", "sv")


def translate(
    node: object, language: str, says: dict[str, dict[str, str]], missing: set[str]
) -> object:
    """The same shape, with every string it has words for put through."""
    if isinstance(node, dict):
        return {
            key: translate(value, language, says, missing)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [translate(value, language, says, missing) for value in node]
    if isinstance(node, str):
        words = says.get(node)
        if words is None or language not in words:
            missing.add(node)
            return node
        return words[language]
    return node


def main() -> int:
    english = json.loads((COMPONENT / "strings.json").read_text())
    says = json.loads(WORDS.read_text())
    missing: set[str] = set()
    for language in LANGUAGES:
        translated = translate(english, language, says, missing)
        (COMPONENT / "translations" / f"{language}.json").write_text(
            json.dumps(translated, indent=2, ensure_ascii=False) + "\n"
        )
    print(f"wrote {len(LANGUAGES)} languages from {len(says)} strings")
    for absent in sorted(missing):
        print(f"  no words for: {absent}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
