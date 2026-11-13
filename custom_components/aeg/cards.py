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


"""The dashboard card this ships, served and made available to add.

A card is put in front of the user as a Lovelace resource, which is what
lists it in the card picker and loads it onto a dashboard, the same way an
installed card is added. Loading it on every page instead does not offer it
in the picker as reliably, and a card that cannot be picked might as well not
ship.

The resource list is loaded from disk before anything is written to it. A
storage-backed list that is written while still unloaded is overwritten whole,
which would take every resource the user already had with it, so the guard
matters more than it looks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Each card is one file under www/, served at /aeg/<file> and offered in the
# picker by the name it gives itself.
CARDS = ("aeg-washer-card.js",)

# Set once the files are being served, so several accounts do not each serve
# them again.
_SERVED = f"{DOMAIN}_cards_served"


def url_of(card: str) -> str:
    """Where one card is served, without the cache-busting version."""
    return f"/{DOMAIN}/{card}"


async def register(hass: HomeAssistant, version: str) -> None:
    """Serve every card and add it to the dashboard's resources, once.

    A card is a convenience, not the integration, so a frontend that will not
    take one is noted and stepped over rather than allowed to stop an account
    being set up.
    """
    if not hass.data.get(_SERVED):
        from homeassistant.components.http import (  # type: ignore[attr-defined]
            StaticPathConfig,
        )

        here = Path(__file__).parent / "www"
        try:
            # The caching resource hands each file over as text/javascript
            # however sparse the host's own list of media types is; the plain
            # one can hand a module over as something a browser will not load.
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(url_of(card), str(here / card), cache_headers=True)
                    for card in CARDS
                ]
            )
        except Exception as err:
            _LOGGER.warning("could not serve the dashboard cards: %s", err)
            return
        hass.data[_SERVED] = True

    # The resource list may not be loaded from disk this early in a start, and
    # writing it before it is loaded loses every other resource. Waiting until
    # the start has finished keeps that window shut.
    async def add_resources(_event: Any = None) -> None:
        await _add_resources(hass, version)

    if hass.state is CoreState.running:
        await add_resources()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, add_resources)


async def _add_resources(hass: HomeAssistant, version: str) -> None:
    """Point the dashboard at every card, adding or freshening each in place.

    A dashboard kept in storage has a list this writes to; one kept in YAML
    has no such list, and its owner adds the resource by hand, which is noted
    and left alone.
    """
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None:
        _LOGGER.debug("no dashboard resources to register the cards with")
        return
    try:
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for card in CARDS:
            await _one(resources, url_of(card), version)
    except AttributeError:
        _LOGGER.debug("dashboard resources are kept in YAML; add the cards by hand")
    except Exception as err:
        _LOGGER.warning("could not register the card resources: %s", err)


async def _one(resources: Any, base: str, version: str) -> None:
    """Add one card as a module resource, or move it to this version.

    The version rides on the url so a new release is fetched rather than read
    from an old cache. An entry from a former version is updated where it
    stands rather than left beside a new one, so the list does not fill with
    a card's every past self.
    """
    wanted = f"{base}?v={version}"
    for item in resources.async_items():
        url = item.get("url")
        if not isinstance(url, str) or not url.startswith(base):
            continue
        if url != wanted:
            await resources.async_update_item(item["id"], {"url": wanted})
        return
    await resources.async_create_item({"res_type": "module", "url": wanted})
