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

"""What to hand over when something is wrong.

Home Assistant offers to download this from the device page, and people paste
it into bug reports, so it carries what is worth knowing and nothing that says
who anyone is. The same redaction the logs use covers it: tokens, keys, the
address on the account and the identifier of the appliance itself.

What it does carry is the whole of what an appliance said about itself, which
is the one thing a report about a model nobody has cannot do without.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import AegConfigEntry
from .capability import platform_for
from .http import redact


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AegConfigEntry
) -> dict[str, Any]:
    """Everything worth knowing about one account."""
    coordinator = entry.runtime_data.coordinator
    return {
        "entry": redact(dict(entry.data)),
        "polling": {
            # Ten minutes means the stream is carrying it, thirty seconds
            # means it is not.
            "every": str(coordinator.update_interval),
            "last_look_worked": coordinator.last_update_success,
        },
        "appliances": [
            {
                "model": appliance.model,
                "connected": appliance.connected,
                "reported": redact(appliance.reported),
                "describes": [
                    {
                        "path": capability.path,
                        "access": capability.access,
                        "type": capability.kind,
                        "becomes": platform_for(capability),
                        "values": list(capability.values),
                        "min": capability.minimum,
                        "max": capability.maximum,
                        "step": capability.step,
                        "disabled": capability.disabled,
                    }
                    for capability in appliance.capabilities
                ],
                "accepts_now": {
                    path: {
                        "access": override.access,
                        "values": list(override.values or ()),
                        "disabled": override.disabled,
                        # What a number will take right now, which is not the
                        # range the field describes and is what decides the
                        # bounds somebody is being offered.
                        "min": override.minimum,
                        "max": override.maximum,
                        "step": override.step,
                    }
                    for path, override in appliance.overrides.items()
                },
            }
            for appliance in coordinator.data.values()
        ],
    }
