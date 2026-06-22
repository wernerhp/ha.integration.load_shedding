"""The LoadShedding component."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta, timezone
import logging
from typing import Any

from load_shedding.libs.sepush import SePush, SePushError
from load_shedding.providers import Area, Stage

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
    CONF_API_KEY,
    CONF_ID,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    __version__ as HA_VERSION,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    API,
    AREA_UPDATE_INTERVAL,
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_PLANNED,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_TIME,
    CONF_AREAS,
    CONF_MIN_EVENT_DURATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    NAME,
    STAGE_UPDATE_INTERVAL,
    VERSION,
)
from .helpers import should_refresh

_LOGGER = logging.getLogger(__name__)

# Appended to diagnostic logs so user-submitted logs identify the integration
# and Home Assistant versions without us having to ask.
DIAG_CONTEXT = f"[load_shedding {VERSION}, Home Assistant {HA_VERSION}]"

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]

_STORE_VERSION = 1


# ---------------------------------------------------------------------------
# Coordinator cache serialisation helpers
# ---------------------------------------------------------------------------
# Stage and area coordinator data contains Stage enums and datetime objects
# that must be flattened to JSON-safe primitives before writing to Store and
# re-inflated after loading.  Deserialization failures are suppressed in the
# callers so a corrupt/incompatible cache silently falls back to a live poll.


def _serialize_stage_data(data: dict) -> dict:
    result: dict = {}
    for zone_id, zone_data in data.items():
        planned = [
            {
                ATTR_STAGE: slot[ATTR_STAGE].value,
                ATTR_START_TIME: slot[ATTR_START_TIME].isoformat(),
                ATTR_END_TIME: slot[ATTR_END_TIME].isoformat(),
            }
            for slot in zone_data.get(ATTR_PLANNED, [])
        ]
        result[zone_id] = {ATTR_NAME: zone_data.get(ATTR_NAME, ""), ATTR_PLANNED: planned}
    return result


def _deserialize_stage_data(stored: dict) -> dict:
    result: dict = {}
    for zone_id, zone_data in stored.items():
        planned = [
            {
                ATTR_STAGE: Stage(int(slot[ATTR_STAGE])),
                ATTR_START_TIME: datetime.fromisoformat(slot[ATTR_START_TIME]),
                ATTR_END_TIME: datetime.fromisoformat(slot[ATTR_END_TIME]),
            }
            for slot in zone_data.get(ATTR_PLANNED, [])
        ]
        result[zone_id] = {ATTR_NAME: zone_data.get(ATTR_NAME, ""), ATTR_PLANNED: planned}
    return result


def _serialize_area_data(data: dict) -> dict:
    # Only events + schedule are persisted; forecast is derived and recomputed.
    result: dict = {}
    for area_id, area_data in data.items():
        events = [
            {
                ATTR_STAGE: s[ATTR_STAGE].value,
                ATTR_START_TIME: s[ATTR_START_TIME].isoformat(),
                ATTR_END_TIME: s[ATTR_END_TIME].isoformat(),
            }
            for s in area_data.get(ATTR_EVENTS, [])
        ]
        schedule: dict[str, list] = {}
        for stage, slots in area_data.get(ATTR_SCHEDULE, {}).items():
            schedule[str(stage.value)] = [
                {
                    ATTR_STAGE: s[ATTR_STAGE].value,
                    ATTR_START_TIME: s[ATTR_START_TIME].isoformat(),
                    ATTR_END_TIME: s[ATTR_END_TIME].isoformat(),
                }
                for s in slots
            ]
        result[area_id] = {ATTR_EVENTS: events, ATTR_SCHEDULE: schedule}
    return result


def _deserialize_area_data(stored: dict) -> dict:
    result: dict = {}
    for area_id, area_data in stored.items():
        events = [
            {
                ATTR_STAGE: Stage(int(s[ATTR_STAGE])),
                ATTR_START_TIME: datetime.fromisoformat(s[ATTR_START_TIME]),
                ATTR_END_TIME: datetime.fromisoformat(s[ATTR_END_TIME]),
            }
            for s in area_data.get(ATTR_EVENTS, [])
        ]
        schedule: dict[Stage, list] = {}
        for stage_val, slots in area_data.get(ATTR_SCHEDULE, {}).items():
            stage = Stage(int(stage_val))
            schedule[stage] = [
                {
                    ATTR_STAGE: Stage(int(s[ATTR_STAGE])),
                    ATTR_START_TIME: datetime.fromisoformat(s[ATTR_START_TIME]),
                    ATTR_END_TIME: datetime.fromisoformat(s[ATTR_END_TIME]),
                }
                for s in slots
            ]
        result[area_id] = {ATTR_EVENTS: events, ATTR_SCHEDULE: schedule}
    return result


# ---------------------------------------------------------------------------
# Integration setup / teardown
# ---------------------------------------------------------------------------


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    _LOGGER.debug("Setting up Load Shedding %s", DIAG_CONTEXT)
    if not hass.data.get(DOMAIN):
        hass.data.setdefault(DOMAIN, {})

    sepush: SePush = None
    if api_key := config_entry.options.get(CONF_API_KEY):
        sepush: SePush = SePush(
            token=api_key,
            user_agent_context={
                "ha_integration_load_shedding": VERSION,
                "homeassistant": HA_VERSION,
            },
        )
    if not sepush:
        _LOGGER.error(
            "Cannot set up Load Shedding: no SePush API key configured. "
            "Add a token under the integration options"
        )
        return False

    # Clear any stale invalid-area-id repair issue if all configured areas are now valid.
    issue_id = f"invalid_area_ids_{config_entry.entry_id}"
    if not any(
        "-" in conf.get(CONF_ID, "")
        for conf in config_entry.options.get(CONF_AREAS, [])
    ):
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    stage_coordinator = LoadSheddingStageCoordinator(
        hass, sepush, config_entry.entry_id
    )
    stage_coordinator.update_interval = timedelta(
        seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    area_coordinator = LoadSheddingAreaCoordinator(
        hass, sepush, stage_coordinator=stage_coordinator,
        entry_id=config_entry.entry_id,
    )
    area_coordinator.update_interval = timedelta(
        seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    for conf in config_entry.options.get(CONF_AREAS, []):
        area = Area(
            id=conf.get(CONF_ID),
            name=conf.get(CONF_NAME),
        )
        area_coordinator.add_area(area)
    if not area_coordinator.areas:
        _LOGGER.error(
            "Cannot set up Load Shedding: no areas configured. "
            "Add at least one area under the integration options"
        )
        return False

    hass.data[DOMAIN][config_entry.entry_id] = {
        ATTR_STAGE: stage_coordinator,
        ATTR_AREA: area_coordinator,
    }

    config_entry.async_on_unload(config_entry.add_update_listener(update_listener))

    # Restore persisted timestamps and data so the first refresh skips the
    # SePush API when the cached values are still within the update interval.
    # This prevents quota exhaustion on every HA restart (#116).
    await stage_coordinator.async_load_cache()
    await area_coordinator.async_load_cache()

    await stage_coordinator.async_config_entry_first_refresh()
    await area_coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Load Shedding Entry from config_entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Remove Load Shedding config entry and wipe persisted coordinator caches."""
    for kind in ("stage", "area"):
        await Store(
            hass, version=_STORE_VERSION, key=f"{DOMAIN}.{kind}.{config_entry.entry_id}"
        ).async_remove()


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Reload config entry."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Update listener."""
    return await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    LATEST_VERSION = 1
    LATEST_MINOR_VERSION = 4
    if (
        config_entry.version == LATEST_VERSION
        and config_entry.minor_version == LATEST_MINOR_VERSION
    ):
        return False

    _LOGGER.debug(
        "Migrating from version %s to %s", config_entry.version, LATEST_VERSION
    )

    if config_entry.version == 3:
        old_data = {**config_entry.data}
        old_options = {**config_entry.options}
        new_data = {}
        new_options = {
            CONF_API_KEY: old_data.get(CONF_API_KEY),
            CONF_AREAS: old_options.get(CONF_AREAS, {}),
        }

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            version=1,
            minor_version=4,
        )

    if config_entry.version == 4:
        old_data = {**config_entry.data}
        old_options = {**config_entry.options}
        new_data = {}
        new_options = {
            CONF_API_KEY: old_options.get(CONF_API_KEY),
            CONF_AREAS: [],
        }
        for field in old_options:
            if field == CONF_AREAS:
                areas = old_options.get(CONF_AREAS, {})
                for area_id in areas:
                    new_options[CONF_AREAS].append(areas[area_id])
                continue

            value = old_options.get(field)
            if value is not None:
                new_options[field] = value

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            version=1,
            minor_version=5,
        )

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


# ---------------------------------------------------------------------------
# Coordinators
# ---------------------------------------------------------------------------


class LoadSheddingStageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding Stage."""

    def __init__(
        self, hass: HomeAssistant, sepush: SePush, entry_id: str | None = None
    ) -> None:
        """Initialize the stage coordinator."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.last_update: datetime | None = None
        self._entry_id = entry_id
        self._store: Store = Store(
            hass, version=_STORE_VERSION, key=f"{DOMAIN}.stage.{entry_id}"
        )

    async def async_load_cache(self) -> None:
        """Pre-seed last_update and data from persistent storage.

        When the cache is fresh (within STAGE_UPDATE_INTERVAL), the first call
        to _async_update_data will return the cached data without hitting the
        SePush API, preventing quota exhaustion on every HA restart (#116).
        """
        stored = await self._store.async_load()
        if not stored:
            return
        with contextlib.suppress(Exception):
            self.last_update = datetime.fromisoformat(stored["last_update"])
            self.data = _deserialize_stage_data(stored.get("data", {}))
            # Seed the SePush rate-limit cache so the quota sensor reads the
            # persisted quota on restart without a blocking refresh, the same
            # way the stage/area data is restored to skip the API (#116).
            if rate_limit := stored.get("rate_limit"):
                self.sepush._rate_limit = rate_limit
            _LOGGER.debug(
                "Restored stage cache (last_update=%s) %s", self.last_update, DIAG_CONTEXT
            )

    async def _save_cache(self) -> None:
        """Persist last_update and data after a successful API poll."""
        await self._store.async_save(
            {
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "data": _serialize_stage_data(self.data),
                # Persist the quota snapshot primed by the status() poll so it
                # can reseed sepush._rate_limit on the next restart.
                "rate_limit": dict(getattr(self.sepush, "_rate_limit", None) or {}),
            }
        )

    async def _async_update_data(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(UTC).replace(microsecond=0)
        if not should_refresh(self.last_update, now, STAGE_UPDATE_INTERVAL):
            return self.data

        try:
            stage = await self.async_update_stage()
        except SePushError as err:
            _LOGGER.error("Unable to get stage: %s %s", err, DIAG_CONTEXT)
            if err.status_code in (400, 403, 429):
                # Back off on permanent/auth/quota failures to avoid retry spam.
                self.last_update = now
            self._create_sepush_issue(err)
            self.data = {}
        except Exception as err:  # noqa: BLE001
            # Covers UpdateFailed and any unexpected error (e.g. a malformed
            # status payload). The failure is logged and surfaced as a Repairs
            # issue rather than silently swallowed.
            _LOGGER.exception("Unexpected error fetching stage %s", DIAG_CONTEXT)
            self._create_sepush_issue(err)
            self.data = {}
        else:
            self.data = stage
            self.last_update = now
            await self._save_cache()
            ir.async_delete_issue(
                self.hass, DOMAIN, f"sepush_api_failure_{self._entry_id}"
            )

        return self.data

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        now = datetime.now(UTC).replace(microsecond=0)
        esp = await self.hass.async_add_executor_job(self.sepush.status)

        data = {}
        statuses = esp.get("status", {})
        for idx, area in statuses.items():
            try:
                stage = Stage(int(area.get("stage", "0")))
                start_time = datetime.fromisoformat(area.get("stage_updated"))
                start_time = start_time.replace(second=0, microsecond=0)
                planned = [
                    {
                        ATTR_STAGE: stage,
                        ATTR_START_TIME: start_time.astimezone(UTC),
                    }
                ]

                next_stages = area.get("next_stages", [])
                for i, next_stage in enumerate(next_stages):
                    # Prev
                    prev_end = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    prev_end = prev_end.replace(second=0, microsecond=0)
                    planned[i][ATTR_END_TIME] = prev_end.astimezone(UTC)

                    # Next
                    stage = Stage(int(next_stage.get("stage", "0")))
                    start_time = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    start_time = start_time.replace(second=0, microsecond=0)
                    planned.append(
                        {
                            ATTR_STAGE: stage,
                            ATTR_START_TIME: start_time.astimezone(UTC),
                        }
                    )

                filtered = []
                for stage in planned:
                    if ATTR_END_TIME not in stage:
                        stage[ATTR_END_TIME] = stage[ATTR_START_TIME] + timedelta(
                            days=7
                        )
                    if ATTR_END_TIME in stage and stage.get(ATTR_END_TIME) >= now:
                        filtered.append(stage)
            except (ValueError, TypeError, KeyError, AttributeError):
                # A malformed entry for one zone must not abort the others.
                _LOGGER.exception(
                    "Unable to parse stage status for '%s' %s", idx, DIAG_CONTEXT
                )
                continue

            data[idx] = {
                ATTR_NAME: area.get("name", ""),
                ATTR_PLANNED: filtered,
            }

        return data

    def _create_sepush_issue(self, err: Exception) -> None:
        """Surface a failed SePush API poll as a Repairs issue.

        Auth/quota/client errors (400/403/429) are user-actionable, so they are
        raised as errors pointing at the token/quota. Any other failure (5xx,
        network problems, timeouts, malformed payloads) is treated as a
        temporary API outage and raised as a warning. Both share one issue id so
        only a single repair is shown at a time, and it clears on recovery.
        """
        status = getattr(err, "status_code", None)
        if status in (400, 403, 429):
            translation_key = "sepush_api_failure"
            severity = ir.IssueSeverity.ERROR
        else:
            translation_key = "sepush_api_unavailable"
            severity = ir.IssueSeverity.WARNING
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"sepush_api_failure_{self._entry_id}",
            is_fixable=False,
            severity=severity,
            translation_key=translation_key,
            translation_placeholders={"error": str(err)},
            learn_more_url=(
                "https://github.com/wernerhp/ha_integration_load_shedding/issues"
            ),
        )


class LoadSheddingAreaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding Area."""

    def __init__(
        self,
        hass: HomeAssistant,
        sepush: SePush,
        stage_coordinator: DataUpdateCoordinator,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the area coordinator."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.last_update: datetime | None = None
        self.areas: list[Area] = []
        self.stage_coordinator = stage_coordinator
        self._entry_id = entry_id
        self._invalid_area_ids: set[str] = set()
        self._store: Store = Store(
            hass, version=_STORE_VERSION, key=f"{DOMAIN}.area.{entry_id}"
        )

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def async_load_cache(self) -> None:
        """Pre-seed last_update and data from persistent storage.

        When the cache is fresh (within AREA_UPDATE_INTERVAL), the first call
        to _async_update_data will skip the SePush API and recompute the
        forecast from the cached schedule, preventing quota exhaustion on every
        HA restart (#116).
        """
        stored = await self._store.async_load()
        if not stored:
            return
        with contextlib.suppress(Exception):
            self.last_update = datetime.fromisoformat(stored["last_update"])
            self.data = _deserialize_area_data(stored.get("data", {}))
            _LOGGER.debug(
                "Restored area cache (last_update=%s) %s", self.last_update, DIAG_CONTEXT
            )

    async def _save_cache(self) -> None:
        """Persist last_update and data after a successful API poll."""
        await self._store.async_save(
            {
                "last_update": self.last_update.isoformat() if self.last_update else None,
                "data": _serialize_area_data(self.data),
            }
        )

    async def _async_update_data(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(UTC).replace(microsecond=0)
        if not should_refresh(self.last_update, now, AREA_UPDATE_INTERVAL):
            await self.async_area_forecast()
            return self.data

        try:
            area = await self.async_update_area()
        except SePushError as err:
            # Keep the previously-fetched schedules rather than wiping them on a
            # transient failure. API health is surfaced as a Repairs issue by the
            # stage coordinator, which polls the same token.
            _LOGGER.error("Unable to get area schedule: %s %s", err, DIAG_CONTEXT)
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Unexpected error fetching area schedule %s", DIAG_CONTEXT
            )
        else:
            # Merge so areas that failed to fetch this cycle keep their previous
            # schedule instead of disappearing until the next update interval.
            self.data = {**self.data, **area}
            self.last_update = now
            await self._save_cache()

        await self.async_area_forecast()
        return self.data

    async def async_update_area(self) -> dict:
        """Retrieve area data."""
        area_id_data: dict = {}

        for area in self.areas:
            if area.id in self._invalid_area_ids:
                _LOGGER.debug(
                    "Skipping permanently-invalid area '%s' (%s)", area.name, area.id
                )
                continue

            try:
                esp = await self.hass.async_add_executor_job(self.sepush.area, area.id)
            except SePushError as err:
                if err.status_code == 400 and "-" in area.id:
                    _LOGGER.warning(
                        "Area '%s' (%s) has a legacy v2 area ID (contains '-'). "
                        "It will be skipped until re-added with a valid v3 ID. %s",
                        area.name,
                        area.id,
                        DIAG_CONTEXT,
                    )
                    self._invalid_area_ids.add(area.id)
                    self._create_invalid_area_issue()
                else:
                    _LOGGER.error(
                        "Unable to get schedule for area '%s' (%s): %s %s",
                        area.name,
                        area.id,
                        err,
                        DIAG_CONTEXT,
                    )
                continue

            try:
                # Get events for area
                events = []
                for event in esp.get("events", {}):
                    note = event.get("note")
                    parts = str(note).split(" ")
                    try:
                        stage = Stage(int(parts[1]))
                    except (ValueError, IndexError):
                        stage = Stage.NO_LOAD_SHEDDING
                        if note == str(Stage.LOAD_REDUCTION):
                            stage = Stage.LOAD_REDUCTION

                    start = datetime.fromisoformat(event.get("start")).astimezone(UTC)
                    end = datetime.fromisoformat(event.get("end")).astimezone(UTC)

                    events.append(
                        {
                            ATTR_STAGE: stage,
                            ATTR_START_TIME: start,
                            ATTR_END_TIME: end,
                        }
                    )

                # Get schedule for area
                stage_schedule = {}
                for day in esp.get("schedule", {}).get("days", []):
                    date = datetime.strptime(day.get("date"), "%Y-%m-%d")
                    stage_timeslots = day.get("stages", [])
                    for i, timeslots in enumerate(stage_timeslots):
                        stage = Stage(i + 1)
                        if stage not in stage_schedule:
                            stage_schedule[stage] = []
                        for timeslot in timeslots:
                            start_str, end_str = timeslot.strip().split("-")
                            start = utc_dt(date, datetime.strptime(start_str, "%H:%M"))
                            end = utc_dt(date, datetime.strptime(end_str, "%H:%M"))
                            if end < start:
                                end = end + timedelta(days=1)
                            stage_schedule[stage].append(
                                {
                                    ATTR_STAGE: stage,
                                    ATTR_START_TIME: start,
                                    ATTR_END_TIME: end,
                                }
                            )
            except (ValueError, TypeError, KeyError, AttributeError):
                # A malformed payload for one area must not abort the others.
                # Log the offending area and full traceback, then skip it; its
                # previous schedule is preserved by the coordinator merge.
                _LOGGER.exception(
                    "Unable to parse schedule for area '%s' (%s) %s",
                    area.name,
                    area.id,
                    DIAG_CONTEXT,
                )
                continue

            area_id_data[area.id] = {
                ATTR_EVENTS: events,
                ATTR_SCHEDULE: stage_schedule,
            }

        return area_id_data

    async def async_area_forecast(self) -> None:
        """Derive area forecast from planned stages and area schedule."""

        cape_town = "capetown"
        eskom = "eskom"

        stages = self.stage_coordinator.data
        eskom_stages = stages.get(eskom, {}).get(ATTR_PLANNED, [])
        cape_town_stages = stages.get(cape_town, {}).get(ATTR_PLANNED, [])

        # Read the configured minimum event duration once, not per timeslot.
        min_event_dur = self.stage_coordinator.config_entry.options.get(
            CONF_MIN_EVENT_DURATION, 30
        )  # minutes
        min_event_duration = timedelta(minutes=min_event_dur)

        for area_id, data in self.data.items():
            stage_schedules = data.get(ATTR_SCHEDULE)

            planned_stages = (
                cape_town_stages if area_id.startswith(cape_town) else eskom_stages
            )
            forecast = []
            for planned in planned_stages:
                planned_stage = planned.get(ATTR_STAGE)
                planned_start_time = planned.get(ATTR_START_TIME)
                planned_end_time = planned.get(ATTR_END_TIME)

                if planned_stage in [Stage.NO_LOAD_SHEDDING]:
                    continue

                schedule = stage_schedules.get(planned_stage, [])

                for timeslot in schedule:
                    start_time = timeslot.get(ATTR_START_TIME)
                    end_time = timeslot.get(ATTR_END_TIME)

                    if start_time >= planned_end_time:
                        continue
                    if end_time <= planned_start_time:
                        continue

                    # Clip schedules that overlap planned start time and end time
                    if (
                        start_time <= planned_start_time
                        and end_time <= planned_end_time
                    ):
                        start_time = planned_start_time
                    if (
                        start_time >= planned_start_time
                        and end_time >= planned_end_time
                    ):
                        end_time = planned_end_time

                    if start_time == end_time:
                        continue

                    # Minimum event duration
                    if end_time - start_time < min_event_duration:
                        continue

                    forecast.append(
                        {
                            ATTR_STAGE: planned_stage,
                            ATTR_START_TIME: start_time,
                            ATTR_END_TIME: end_time,
                        }
                    )

            if not forecast:
                events = data.get(ATTR_EVENTS)

                for timeslot in events:
                    stage = timeslot.get(ATTR_STAGE)
                    start_time = timeslot.get(ATTR_START_TIME)
                    end_time = timeslot.get(ATTR_END_TIME)

                    # Minimum event duration
                    if end_time - start_time < min_event_duration:
                        continue

                    forecast.append(
                        {
                            ATTR_STAGE: stage,
                            ATTR_START_TIME: start_time,
                            ATTR_END_TIME: end_time,
                        }
                    )

            data[ATTR_FORECAST] = forecast

    def _create_invalid_area_issue(self) -> None:
        """Create a Repairs issue listing all permanently-invalid area IDs."""
        invalid_names = [
            a.name for a in self.areas if a.id in self._invalid_area_ids
        ]
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"invalid_area_ids_{self._entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="invalid_area_ids",
            translation_placeholders={"areas": ", ".join(invalid_names)},
            learn_more_url=(
                "https://github.com/wernerhp/ha_integration_load_shedding/issues"
            ),
        )


def utc_dt(date: datetime, time: datetime) -> datetime:
    """Given a date and time in SAST, this function returns a datetime object in UTC."""
    sast = timezone(timedelta(hours=+2), "SAST")

    return time.replace(
        year=date.year,
        month=date.month,
        day=date.day,
        second=0,
        microsecond=0,
        tzinfo=sast,
    ).astimezone(UTC)


class LoadSheddingDevice(Entity):
    """Define a LoadShedding device."""

    def __init__(self, coordinator) -> None:
        """Initialize the device."""
        super().__init__(coordinator)
        self.device_id = "{NAME}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self.device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_SW_VERSION: VERSION,
        }
