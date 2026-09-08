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

"""Work out where each named field turns up, and write the text out.

A name is only used where Home Assistant has been given the text for it, and
where it has been given it per platform, so this reads every capability tree to
hand and records which platforms each named field is known to become. It writes
the block at the bottom of names.py and the entity section of strings.json.

    python tools/make_names.py

Run it after adding a name, or after a new capability tree turns up.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from glob import glob
from pathlib import Path

sys.path.insert(0, ".")

from custom_components.aeg.capability import parse, platform_for
from custom_components.aeg.names import NAMES, PLATFORMS_FOR, key_for, readable

COMPONENT = Path("custom_components/aeg")
TREES = ["tests/fixtures/*-capabilities.json", "tmp/base/assets/*capabilities*.json"]


def _trees() -> list[Path]:
    found: list[Path] = []
    for pattern in TREES:
        found += [Path(p) for p in sorted(glob(pattern))]
    return [path for path in found if path.is_file()]


def _where() -> dict[str, set[str]]:
    """Which platforms each named field is known to become."""
    seen: dict[str, set[str]] = defaultdict(set)
    for tree in _trees():
        for capability in parse(json.loads(tree.read_text())):
            platform = platform_for(capability)
            if platform and readable(capability.name):
                seen[key_for(capability.name)].add(platform)
    return seen


def _lost(seen: dict[str, set[str]]) -> list[str]:
    """Named fields that none of the trees to hand says anything about.

    Most of the trees are the ones the app ships, and those live under tmp,
    which is not in the repository. A checkout on its own sees only the two
    the tests use, and writing what those alone say would quietly take the
    text for two thirds of the named fields out of Home Assistant, and out of
    every translation of it.
    """
    named = {key_for(field) for field in NAMES}
    return sorted(key for key in PLATFORMS_FOR if key in named and key not in seen)


def _write_names(seen: dict[str, set[str]]) -> None:
    path = COMPONENT / "names.py"
    body = path.read_text()
    marker = "PLATFORMS_FOR: dict[str, frozenset[str]] = "
    lines = [f"{marker}{{"]
    for key in sorted(seen):
        platforms = ", ".join(f'"{p}"' for p in sorted(seen[key]))
        lines.append(f'    "{key}": frozenset({{{platforms}}}),')
    lines.append("}")
    path.write_text(body[: body.index(marker)] + "\n".join(lines) + "\n")


def _write_strings(seen: dict[str, set[str]]) -> None:
    by_platform: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for field, name in NAMES.items():
        key = key_for(field)
        for platform in sorted(seen.get(key, ())):
            by_platform[platform][key] = {"name": name}
    for path in (COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"):
        text = json.loads(path.read_text())
        text["entity"] = {
            platform: dict(sorted(keys.items()))
            for platform, keys in sorted(by_platform.items())
        }
        path.write_text(json.dumps(text, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    trees = _trees()
    if not trees:
        print("no capability trees to read")
        return 1
    seen = _where()
    if lost := _lost(seen):
        print(f"nothing written: {len(trees)} trees to hand say nothing about")
        print(f"{len(lost)} fields that are named and placed already:")
        for key in lost:
            print(f"  {key}")
        print("unpack the app into tmp/base, or take the names out first")
        return 1
    _write_names(seen)
    _write_strings(seen)
    print(f"{len(seen)} named fields, from {len(trees)} trees")
    for platform in sorted({p for places in seen.values() for p in places}):
        count = sum(1 for places in seen.values() if platform in places)
        print(f"  {platform:14} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
