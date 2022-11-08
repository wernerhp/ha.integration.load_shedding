"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_SW_VERSION,
    CONF_API_KEY,
    CONF_ID,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_VIA_DEVICE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from load_shedding.libs.sepush import SePush, SePushError
from load_shedding.providers import Area, Stage, to_utc
from .const import (
    API,
    API_UPDATE_INTERVAL,
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_PLANNED,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_STAGE_DATA,
    ATTR_START_TIME,
    CONF_AREAS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    NAME,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    api_key: str = entry.data.get(CONF_API_KEY)
    sepush: SePush = SePush(token=api_key)
    if not hass.data.get(DOMAIN):
        hass.data.setdefault(DOMAIN, {})

    coordinator = LoadSheddingCoordinator(hass, sepush)
    coordinator.update_interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    for conf in entry.options.get(CONF_AREAS, []).values():
        area = Area(
            id=conf.get(CONF_ID),
            name=conf.get(CONF_NAME),
        )
        coordinator.add_area(area)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Load Shedding Entry from config_entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Update listener."""
    return await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


class LoadSheddingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding stage from Provider."""

    def __init__(self, hass: HomeAssistant, sepush: SePush) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.areas: list[Area] = []
        self.last_update: datetime | None = None

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def _async_update_data(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(timezone.utc).replace(microsecond=0)
        diff = 0
        if self.last_update is not None:
            diff = (now - self.last_update).seconds

        if 0 < diff < API_UPDATE_INTERVAL:
            return self.data

        try:
            data = await self.async_update_stage()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get stage: %s", err, exc_info=True)
            self.data[ATTR_STAGE] = {}
        else:
            self.data[ATTR_STAGE] = data
            self.last_update = now

        try:
            data = await self.async_update_schedule()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get schedule: %s", err, exc_info=True)
            self.data[ATTR_AREA] = []
        else:
            self.data[ATTR_AREA] = data
            self.last_update = now

        try:
            await self.async_area_forecast()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get schedule: %s", err, exc_info=True)

        try:
            data = await self.async_update_quota()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get quota: %s", err, exc_info=True)
            self.data[ATTR_QUOTA] = {}
        else:
            self.data[ATTR_QUOTA] = data
            self.last_update = now

        return self.data

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            esp = await self.hass.async_add_executor_job(self.sepush.status)
        except SePushError as err:
            raise UpdateFailed(err) from err
        else:
            data = {}
            statuses = esp.get("status", {})
            for idx, area in statuses.items():
                planned = [
                    {
                        ATTR_STAGE: Stage(int(area.get("stage", "0"))),
                        ATTR_START_TIME: datetime.fromisoformat(
                            area.get("stage_updated")
                        ).astimezone(timezone.utc),
                    }
                ]

                next_stages = area.get("next_stages", [])
                for i, next_stage in enumerate(next_stages):
                    # Prev
                    prev_end = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    planned[i][ATTR_END_TIME] = prev_end.astimezone(timezone.utc)

                    # Next
                    planned.append(
                        {
                            ATTR_STAGE: Stage(int(next_stage.get("stage", "0"))),
                            ATTR_START_TIME: datetime.fromisoformat(
                                next_stage.get("stage_start_timestamp")
                            ).astimezone(timezone.utc),
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

                data[idx] = {
                    ATTR_NAME: area.get("name", ""),
                    ATTR_PLANNED: filtered,
                }

        return data

    async def async_update_schedule(self) -> dict:
        """Retrieve schedule data."""
        areas_stage_schedules: dict = {}

        for area in self.areas:
            # Get forecast for area
            events = []
            try:
                data = await self.hass.async_add_executor_job(self.sepush.area, area.id)
            except SePushError as err:
                raise UpdateFailed(err) from err

            for event in data.get("events", {}):
                note = event.get("note")
                parts = str(note).split(" ")
                stage = Stage(int(parts[1]))
                start = datetime.fromisoformat(event.get("start")).astimezone(
                    timezone.utc
                )
                end = datetime.fromisoformat(event.get("end")).astimezone(timezone.utc)

                events.append(
                    {
                        ATTR_STAGE: stage,
                        ATTR_START_TIME: start,
                        ATTR_END_TIME: end,
                    }
                )

            # Get schedule for area
            stage_schedule = {}
            sast = timezone(timedelta(hours=+2), "SAST")
            for day in data.get("schedule", {}).get("days", []):
                date = datetime.strptime(day.get("date"), "%Y-%m-%d")
                stage_timeslots = day.get("stages", [])
                for i, timeslots in enumerate(stage_timeslots):
                    stage = Stage(i + 1)
                    if stage not in stage_schedule:
                        stage_schedule[stage] = []
                    for timeslot in timeslots:
                        start_str, end_str = timeslot.strip().split("-")
                        start = (
                            datetime.strptime(start_str, "%H:%M")
                            .replace(
                                year=date.year,
                                month=date.month,
                                day=date.day,
                                second=0,
                                microsecond=0,
                                tzinfo=sast,
                            )
                            .astimezone(timezone.utc)
                        )
                        end = (
                            datetime.strptime(end_str, "%H:%M")
                            .replace(
                                year=date.year,
                                month=date.month,
                                day=date.day,
                                second=0,
                                microsecond=0,
                                tzinfo=sast,
                            )
                            .astimezone(timezone.utc)
                        )
                        if end < start:
                            end = end + timedelta(days=1)
                        stage_schedule[stage].append(
                            {
                                ATTR_STAGE: stage,
                                ATTR_START_TIME: start,
                                ATTR_END_TIME: end,
                            }
                        )

            areas_stage_schedules[area.id] = {
                ATTR_EVENTS: events,
                ATTR_SCHEDULE: stage_schedule,
            }

        return areas_stage_schedules

    async def async_area_forecast(self) -> None:
        """Derive area forecast from planned stages and area schedule."""

        CAPE_TOWN = "capetown"
        ESKOM = "eskom"

        stages = self.data.get(ATTR_STAGE, {})
        eskom_stages = stages.get(ESKOM, {}).get(ATTR_PLANNED, [])
        cape_town_stages = stages.get(CAPE_TOWN, {}).get(ATTR_PLANNED, [])

        areas = self.data.get(ATTR_AREA, {})
        for area_id, data in areas.items():
            stage_schedules = data.get(ATTR_SCHEDULE)

            planned_stages = (
                cape_town_stages if area_id.startswith(CAPE_TOWN) else eskom_stages
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

                    forecast.append(
                        {
                            ATTR_STAGE: planned_stage,
                            ATTR_START_TIME: start_time,
                            ATTR_END_TIME: end_time,
                        }
                    )

            data[ATTR_FORECAST] = forecast

    async def async_update_quota(self) -> dict:
        """Retrieve latest quota."""
        try:
            data = await self.hass.async_add_executor_job(self.sepush.check_allowance)
        except SePushError as err:
            raise UpdateFailed(err) from err

        return data.get("allowance", {})


class LoadSheddingDevice(Entity):
    """Define a LoadShedding device."""

    def __init__(self, coordinator):
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
            ATTR_VIA_DEVICE: (DOMAIN, self.device_id),
        }
