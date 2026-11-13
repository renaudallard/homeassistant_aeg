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

"""The dashboard cards, served from the integration and added to the dashboard."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from custom_components.aeg import cards

WWW = Path(cards.__file__).parent / "www"


def test_every_card_listed_ships() -> None:
    """A card listed but missing from www/ would be served as a 404."""
    for card in cards.CARDS:
        assert (WWW / card).is_file(), card


async def test_the_cards_are_served_once(hass: HomeAssistant) -> None:
    """The cards ship with the integration and are served from it, so there
    is no file to host by hand, and only once however many accounts are set
    up. The file's former name is served too, for a dashboard naming it by
    hand."""
    hass.data.pop("lovelace", None)
    hass.http = AsyncMock()
    await cards.register(hass, "1.2.3")
    await cards.register(hass, "1.2.3")

    hass.http.async_register_static_paths.assert_awaited_once()
    (paths,) = hass.http.async_register_static_paths.await_args.args
    # With the caching resource, so the module goes out as text/javascript
    # rather than a type the browser will not load.
    served = {path.url_path: (path.path, path.cache_headers) for path in paths}
    assert served == {
        "/aeg/aeg-cards.js": (str(WWW / "aeg-cards.js"), True),
        "/aeg/aeg-washer-card.js": (str(WWW / "aeg-cards.js"), True),
    }


class _Resources:
    """A stand-in for the dashboard's own resource list."""

    def __init__(self) -> None:
        self.loaded = True
        self.items: list[dict[str, str]] = []
        self.created: list[dict[str, str]] = []
        self.updated: list[tuple[str, dict[str, str]]] = []

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict[str, str]]:
        return list(self.items)

    async def async_create_item(self, data: dict[str, str]) -> dict[str, str]:
        item = {"id": f"id{len(self.items)}", **data}
        self.items.append(item)
        self.created.append(data)
        return item

    async def async_update_item(self, item_id: str, changes: dict[str, str]) -> None:
        self.updated.append((item_id, changes))
        for item in self.items:
            if item["id"] == item_id:
                item.update(changes)


async def test_a_card_is_added_then_freshened_in_place() -> None:
    """A card missing from the dashboard is added as a module; one already
    there is moved to the running version rather than added a second time, so
    the list does not fill with a card's every past self."""
    url = "/aeg/aeg-cards.js"
    resources = _Resources()

    await cards._one(resources, url, "1.0.0")
    assert resources.created == [{"res_type": "module", "url": f"{url}?v=1.0.0"}]

    # The same version again touches nothing.
    await cards._one(resources, url, "1.0.0")
    assert len(resources.created) == 1
    assert resources.updated == []

    # A new version freshens the one entry in place.
    await cards._one(resources, url, "1.1.0")
    assert len(resources.created) == 1
    assert resources.updated == [("id0", {"url": f"{url}?v=1.1.0"})]


async def test_the_entry_under_the_former_name_is_moved_onto_the_new_one(
    hass: HomeAssistant,
) -> None:
    """2026.11.1 added the washer card as aeg-washer-card.js. Its entry is
    pointed at the file that holds every card now, in place, so the dashboard
    neither loses the washer card nor loads it twice."""
    resources = _Resources()
    resources.items.append({"id": "old", "url": "/aeg/aeg-washer-card.js?v=2026.11.1"})
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    await cards._add_resources(hass, "2026.11.2")
    assert resources.created == []
    assert resources.updated == [("old", {"url": "/aeg/aeg-cards.js?v=2026.11.2"})]


async def test_registering_the_card_without_a_dashboard_is_harmless(
    hass: HomeAssistant,
) -> None:
    """A system with no storage dashboard has nothing to register the card
    with, which is stepped over rather than raised."""
    hass.data.pop("lovelace", None)
    await cards._add_resources(hass, "1.0.0")


async def test_the_card_waits_for_the_start_when_asked_early(
    hass: HomeAssistant,
) -> None:
    """Asked before the start has finished, the resource registration waits
    for it rather than writing to a list that is not loaded yet."""
    resources = _Resources()
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    hass.http = AsyncMock()
    hass.set_state(CoreState.not_running)
    try:
        await cards.register(hass, "1.2.3")
        # Served at once, but the dashboard is touched only after the start.
        hass.http.async_register_static_paths.assert_awaited_once()
        assert resources.created == []
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        assert len(resources.created) == len(cards.CARDS)
    finally:
        hass.set_state(CoreState.running)
        hass.data.pop("lovelace", None)


async def test_the_card_is_registered_with_a_storage_dashboard(
    hass: HomeAssistant,
) -> None:
    """A storage dashboard keeps a resource list; the card is added to it,
    and anything unrelated already there is left alone."""
    resources = _Resources()
    resources.items.append({"id": "other", "url": "/local/unrelated.js"})
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    await cards._add_resources(hass, "1.0.0")
    urls = {item["url"] for item in resources.items}
    assert urls == {"/local/unrelated.js", "/aeg/aeg-cards.js?v=1.0.0"}
    assert resources.updated == []


async def test_the_card_on_a_yaml_dashboard_is_left_to_its_owner(
    hass: HomeAssistant,
) -> None:
    """A YAML dashboard's resources have no list to write to; that is noted
    and stepped over rather than raised."""
    hass.data["lovelace"] = SimpleNamespace(resources=object())
    await cards._add_resources(hass, "1.0.0")


async def test_an_unloaded_resource_list_is_loaded_before_writing(
    hass: HomeAssistant,
) -> None:
    """A list not yet read from disk is loaded first, so writing the card
    does not lose every other resource."""
    resources = _Resources()
    resources.loaded = False
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    await cards._add_resources(hass, "1.0.0")
    assert resources.loaded is True
    assert len(resources.created) == len(cards.CARDS)


async def test_a_dashboard_that_errors_is_logged_not_raised(
    hass: HomeAssistant,
) -> None:
    """Anything unexpected from the resource list is logged and stepped over,
    not allowed to take the setup down with it."""

    class Boom:
        loaded = True

        def async_items(self) -> list[dict[str, str]]:
            raise RuntimeError("the list would not read")

    hass.data["lovelace"] = SimpleNamespace(resources=Boom())
    await cards._add_resources(hass, "1.0.0")
