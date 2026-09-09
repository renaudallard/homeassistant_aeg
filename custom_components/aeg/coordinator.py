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

"""Keeping one account's appliances up to date.

The appliance list carries the reported state of everything on the account, so
one call refreshes them all. Capabilities are fetched once when the entry is
set up: they describe the model rather than its state, and they are large.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AegApi
from .capability import RUNNING, STATE, Capability, counts_down, number, parse, value_at
from .const import BRANDS, DOMAIN
from .errors import AegAuthError, AegError
from .triggers import Override, evaluate
from .websocket import AegStream, apply

_LOGGER = logging.getLogger(__name__)

# Bump when a capability tree read from the store would no longer be
# understood. Anything written under another version is thrown away rather
# than migrated, so the next start fetches instead of trusting it.
STORE_VERSION = 1

# What a group of settings says it is a setting of.
PROGRAMME = "programUID"

SCAN_INTERVAL = timedelta(seconds=30)
# Once the cloud is really pushing, polling is only there to catch what a
# dropped connection missed.
SCAN_INTERVAL_STREAMING = timedelta(minutes=10)

# How little can be left before it is worth arranging to look again, and how
# long after that to leave it. A minute covers an appliance that counts in
# minutes, whose last figure before zero is sixty.
NEARLY_DONE = 60.0
AFTER_THE_END = timedelta(seconds=70)


class CapabilityStore(Store[dict[str, Any]]):
    """What each appliance said it can do, kept between starts.

    Nothing in here is worth migrating. A tree written under a version that
    read it differently is thrown away and asked for again, which costs one
    call per appliance and is the whole point of the version above.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep nothing, so that everything is read afresh."""
        return {}


def capability_store(hass: HomeAssistant, entry: ConfigEntry) -> CapabilityStore:
    """Where an account's capability trees are kept between starts."""
    return CapabilityStore(
        hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.capabilities"
    )


# Where an appliance keeps the version its network unit is running. The unit
# shouts its state under networkInterface; the newer models keep a group of
# their own and write the same thing in camel case. The first of these an
# appliance reports is the one it means.
FIRMWARE = ("networkInterface/swVersion", "swVersions/niu/ver")


@dataclass
class Appliance:
    """One appliance, what it can do and what it is doing."""

    id: str
    name: str
    model: str
    info: dict[str, Any]
    capabilities: list[Capability]
    reported: dict[str, Any]
    connected: bool
    overrides: dict[str, Override]

    @property
    def sold_as(self) -> str:
        """The model on the box, or the kind of thing it is if that is all we have.

        A listing gives the appliance type and calls it the model name, so an
        account of washing machines is an account of appliances all called WM.
        """
        model = self.info.get("model")
        return str(model) if model else self.model

    @property
    def product_number(self) -> str | None:
        """The number the manufacturer knows this model by.

        The PNC on the rating plate, which is what a parts list or a service
        call is looked up by. It says nothing about which machine is this one.
        """
        pnc = self.info.get("pnc")
        return str(pnc) if pnc else None

    @property
    def made_by(self) -> str | None:
        """Which brand made it, as the appliance itself says.

        Written the way this writes the two brands it signs in as, the cloud
        not being consistent about the case, and left exactly as it came for
        anything else. An account can hold an appliance of a brand this was
        never built for, and calling that one of the two would be a lie.
        """
        brand = self.info.get("brand")
        if not brand:
            return None
        known = BRANDS.get(str(brand).lower())
        return known.name if known else str(brand)

    def first_of(self, paths: tuple[str, ...]) -> Any:
        """What this appliance says, from the first of these it says anything at.

        Two vocabularies turn up for the same handful of things, and which one
        an appliance uses is not worth asking twice about at every call site.
        """
        for path in paths:
            found = value_at(self.reported, path)
            if found is not None:
                return found
        return None

    @property
    def firmware(self) -> str | None:
        """The version its network unit is running, which is what updates."""
        version = self.first_of(FIRMWARE)
        return None if version is None else str(version)

    @cached_property
    def state_path(self) -> str | None:
        """Where this appliance keeps what it is doing.

        Most write applianceState at the top level. An air conditioner keeps it
        under airConditioner, an air purifier under airPurifier and a robot
        vacuum under robot, and which group it is belongs to the appliance, so
        the field is found by the name it goes by in what the appliance
        describes rather than looked for in a list of the places models have
        been seen putting it.

        Held for the life of this reading of the appliance, which is what the
        capabilities are fixed for. A pushed change replaces what is reported
        and not what is described, so the path cannot go stale under it.
        """
        for capability in self.capabilities:
            if capability.name == STATE:
                return capability.path
        return None

    @property
    def doing(self) -> Any:
        """What the appliance says it is doing, or nothing if it will not say."""
        path = self.state_path
        return None if path is None else value_at(self.reported, path)

    @property
    def running(self) -> bool:
        """Whether it says it is doing the thing it counts down to.

        The word is compared without regard to case: a washing machine shouts
        RUNNING where an air conditioner writes running.
        """
        return str(self.doing).upper() == RUNNING


def _nearly_done(appliance: Appliance) -> bool:
    """Whether the appliance is about to finish what it says it is doing.

    Only while it is actually running. A machine that has finished puts the
    length of the programme it is set to back where the time left was, and
    that is not an ending to wait for.
    """
    if not appliance.running:
        return False
    return any(
        left is not None and 0 <= left <= NEARLY_DONE
        for left in (
            number(value_at(appliance.reported, capability.path))
            for capability in appliance.capabilities
            if counts_down(capability)
        )
    )


class AegCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Polls the account and hands out the state of each appliance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AegApi,
        session: aiohttp.ClientSession,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="AEG",
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self._session = session
        # A capability tree is fifty kilobytes and describes the model rather
        # than what it is doing, so it is kept between starts and fetched only
        # when the appliance says it has changed.
        self._store = capability_store(hass, entry)
        self._stream: AegStream | None = None
        self._capabilities: dict[str, list[Capability]] = {}
        # Which fields each appliance has been seen reporting, ever. A field
        # it describes and has never reported is one this model does not have.
        self._seen: dict[str, set[str]] = {}
        # What each appliance is, as opposed to what it is doing.
        self._info: dict[str, dict[str, Any]] = {}
        # A look arranged for after an appliance finishes what it is doing,
        # by the appliance it is about.
        self._endings: dict[str, CALLBACK_TYPE] = {}
        # The listing read while setting up, waiting for the first update.
        self._listed: list[dict[str, Any]] | None = None

    def seen(self, appliance_id: str) -> set[str]:
        """The fields this appliance has been known to report."""
        return self._seen.get(appliance_id, set())

    async def _async_setup(self) -> None:
        """Read what each appliance can do, once.

        An appliance publishes a hash of its own capabilities alongside them,
        which is what makes keeping the last one worth anything: the tree is
        fetched again only when that hash says it is worth fetching.

        What it has reported is kept alongside, because a field missing from
        one answer is not a field the model lacks, and telling those two apart
        needs more than the answer in hand. So is what the appliance is, which
        is one answer for the life of the machine.
        """
        held = await self._store.async_load() or {}
        # An appliance this listing did not mention keeps what is held for it,
        # for the same reason its entities do. Starting it over would lose the
        # fields it has been seen reporting, and the next listing that had it
        # back while it was idle would read that as a machine which had never
        # had them and take them away.
        keeping: dict[str, Any] = dict(held)
        try:
            listed = await self.api.appliances()
            for entry in listed:
                appliance_id = str(entry.get("applianceId", ""))
                if not appliance_id:
                    continue
                reported = (entry.get("properties") or {}).get("reported") or {}
                fingerprint = value_at(reported, "applianceInfo/capabilityHash")
                known = held.get(appliance_id)
                if fingerprint and known and known.get("hash") == fingerprint:
                    tree = known["tree"]
                    _LOGGER.debug("%s describes what it did last time", appliance_id)
                else:
                    tree = await self.api.capabilities(appliance_id)
                    _LOGGER.debug("%s describes %d fields", appliance_id, len(tree))
                capabilities = parse(tree)
                seen = (
                    {str(path) for path in known.get("seen") or ()} if known else set()
                )
                seen |= {
                    capability.path
                    for capability in capabilities
                    if value_at(reported, capability.path) is not None
                }
                info = (known or {}).get("info") or await self._what_it_is(appliance_id)
                keeping[appliance_id] = {
                    "hash": fingerprint,
                    "tree": tree,
                    "seen": sorted(seen),
                }
                if info:
                    # An answer we did not get is not an answer that there is
                    # nothing to say, so keeping the emptiness would be
                    # deciding never to ask again.
                    keeping[appliance_id]["info"] = info
                self._capabilities[appliance_id] = capabilities
                self._seen[appliance_id] = seen
                self._info[appliance_id] = info
            # The account has just been listed, and the first update follows
            # this at once, so it reads what arrived here rather than asking
            # for the same answer again.
            self._listed = listed
        except AegAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AegError as err:
            raise UpdateFailed(str(err)) from err

        if keeping != held:
            await self._store.async_save(keeping)

    async def _what_it_is(self, appliance_id: str) -> dict[str, Any]:
        """What the appliance is, or nothing when the cloud will not say.

        Worth having and not worth failing an account over: without it an
        appliance goes on being known by the type its listing gives, which is
        where it stood before this was asked for at all.

        A refusal here is not the account being refused, which is why even that
        is let go of. The listing was read moments ago on the same token, so
        anything turned down at this one path is that path saying no rather
        than the credentials going stale, and sending somebody to sign in again
        over the model name would cost more than the model name is worth.
        """
        try:
            return await self.api.appliance_info(appliance_id)
        except AegError as err:
            _LOGGER.debug("%s will not say what it is: %s", appliance_id, err)
            return {}

    async def _async_update_data(self) -> dict[str, Appliance]:
        listed, self._listed = self._listed, None
        if listed is None:
            try:
                listed = await self.api.appliances()
            except AegAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except AegError as err:
                raise UpdateFailed(str(err)) from err

        appliances: dict[str, Appliance] = {}
        for entry in listed:
            appliance_id = str(entry.get("applianceId", ""))
            if not appliance_id:
                continue
            data = entry.get("applianceData") or {}
            properties = entry.get("properties") or {}
            appliances[appliance_id] = Appliance(
                id=appliance_id,
                name=str(data.get("applianceName") or "AEG appliance"),
                model=str(data.get("modelName") or "appliance"),
                info=self._info.get(appliance_id, {}),
                capabilities=self._capabilities.get(appliance_id, []),
                reported=properties.get("reported") or {},
                connected=entry.get("connectionState") == "connected",
                overrides={},
            )
        self._refresh_overrides(appliances)
        self._look_again_when_it_ends(appliances)
        self._notice_new(appliances)
        for appliance in appliances.values():
            # The one line worth having when an appliance goes quiet, which is
            # the far end of an answer too long to log whole.
            _LOGGER.debug(
                "%s is %s, %s, reporting %d fields",
                appliance.model,
                "reachable" if appliance.connected else "not reachable",
                appliance.doing or "saying nothing of its state",
                len(appliance.reported),
            )
        return appliances

    def _notice_new(self, appliances: dict[str, Appliance]) -> None:
        """Load the account again when an appliance has been added to it.

        What an appliance can do is read once, while the entry is being set
        up, so one that turned up afterwards has no capabilities, no entities
        of its own and no place in the stream. Reading them means setting the
        entry up again, which is not something an update can do for itself.
        """
        entry = self.config_entry
        added = set(appliances) - set(self._capabilities)
        if not added or entry is None:
            return
        _LOGGER.debug(
            "%d appliance(s) added to the account, loading it again", len(added)
        )
        self.hass.config_entries.async_schedule_reload(entry.entry_id)

    def _refresh_overrides(self, appliances: dict[str, Appliance]) -> None:
        """Work out what each appliance will accept in the state it is in."""
        for appliance in appliances.values():
            appliance.overrides = evaluate(appliance.capabilities, appliance.reported)

    @callback
    def _look_again_when_it_ends(self, appliances: dict[str, Appliance]) -> None:
        """Arrange a look at an appliance that is about to finish.

        A cycle ending is the one change the cloud is least reliable about. It
        goes on pushing the door and the connection while saying nothing about
        the wash, so a machine can be left reporting a minute to go and be
        found still saying it an hour later. Polling would catch that, but the
        stream working is exactly what makes polling ease off to ten minutes,
        so the moment it matters most is the moment we ask least often.

        Which field is counting down is the appliance's own to say, the same
        one the countdown sensor reads. One look is arranged per appliance and
        not another until it has been taken, so a machine counting in seconds
        does not book sixty of them on its way to zero.
        """
        entry = self.config_entry
        if entry is None:
            return
        for appliance in appliances.values():
            if appliance.id in self._endings or not _nearly_done(appliance):
                continue

            @callback
            def _look(_now: datetime, appliance_id: str = appliance.id) -> None:
                self._endings.pop(appliance_id, None)
                _LOGGER.debug("%s should have finished, looking", appliance_id)
                entry.async_create_task(
                    self.hass, self.async_request_refresh(), "AEG look"
                )

            self._endings[appliance.id] = async_call_later(
                self.hass, AFTER_THE_END, _look
            )

    @callback
    def stop_waiting(self) -> None:
        """Give up on any look arranged for after a cycle ends."""
        for cancel in self._endings.values():
            cancel()
        self._endings.clear()

    def start_stream(self, url: str) -> None:
        """Ask the cloud to push changes rather than waiting to be asked."""
        entry = self.config_entry
        if self._stream is not None or not url or not self.data or entry is None:
            return
        self._stream = AegStream(
            self._session,
            url,
            self.api.authorization,
            self.api.seconds_until_renewal,
            list(self.data),
            self._pushed,
            self._streaming,
        )
        self._stream.start(
            lambda watching: entry.async_create_background_task(
                self.hass, watching, "AEG appliance stream"
            )
        )

    async def stop_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await stream.stop()

    def _pushed(self, message: dict[str, Any]) -> None:
        """Fold a pushed change into what we hold and tell the entities."""
        touched = apply(
            message, {key: value.reported for key, value in self.data.items()}
        )
        if touched:
            # Something arrived, so the stream is not merely open, it is
            # working, and polling can ease off behind it.
            self.update_interval = SCAN_INTERVAL_STREAMING
            # What the appliance will accept moves with its state.
            self._refresh_overrides(self.data)
            self._look_again_when_it_ends(self.data)
            self.async_set_updated_data(self.data)

    def _streaming(self, connected: bool) -> None:
        """Back to asking regularly whenever the stream is not carrying us.

        Opening a connection is not the same as being told anything over it. A
        stream the cloud accepts and then says nothing on would otherwise leave
        an appliance being looked at once every ten minutes, which reads as an
        integration that has stopped working.
        """
        entry = self.config_entry
        if connected or self.update_interval == SCAN_INTERVAL or entry is None:
            return
        self.update_interval = SCAN_INTERVAL
        # How often to ask is not when to ask next: the look already scheduled
        # is still ten minutes out, and shortening the interval does not bring
        # it forward. Asking now is what does, and the entry owns the asking so
        # that a stream dropping as the entry goes away leaves nothing behind
        # to ask about an account that has gone.
        entry.async_create_task(self.hass, self.async_request_refresh(), "AEG look")

    async def send(self, appliance_id: str, path: str, value: Any) -> None:
        """Send one field, nested the way the appliance reports it back.

        A group is sent with the programme it belongs to. A washing machine
        holds its wash settings under one, and changing one of them without
        saying which programme it is a setting of is not something it takes.
        """
        command: dict[str, Any] = {}
        target = command
        segments = path.split("/")
        appliance = self.data.get(appliance_id)
        # Which group we are in, written the way the appliance reports it, so
        # that a group inside a group is looked up where it actually sits.
        group = ""
        for segment in segments[:-1]:
            group = f"{group}/{segment}" if group else segment
            target = target.setdefault(segment, {})
            if appliance is not None:
                belongs_to = value_at(appliance.reported, f"{group}/{PROGRAMME}")
                if belongs_to is not None:
                    target[PROGRAMME] = belongs_to
        target[segments[-1]] = value
        await self.api.send_command(appliance_id, command)
        await self.async_request_refresh()
