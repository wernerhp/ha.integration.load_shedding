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
    AREA_UPDATE_INTERVAL,
    STAGE_UPDATE_INTERVAL,
    QUOTA_UPDATE_INTERVAL,
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_PLANNED,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_TIME,
    CONF_AREAS,
    CONF_MIN_EVENT_DURATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    NAME,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.CALENDAR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    if not hass.data.get(DOMAIN):
        hass.data.setdefault(DOMAIN, {})

    sepush: SePush = None
    if api_key := config_entry.options.get(CONF_API_KEY):
        sepush: SePush = SePush(token=api_key)
    if not sepush:
        return False

    stage_coordinator = LoadSheddingStageCoordinator(hass, sepush)
    stage_coordinator.update_interval = timedelta(
        seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    area_coordinator = LoadSheddingAreaCoordinator(
        hass, sepush, stage_coordinator=stage_coordinator
    )
    area_coordinator.update_interval = timedelta(
        seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    for conf in config_entry.options.get(CONF_AREAS, {}).values():
        area = Area(
            id=conf.get(CONF_ID),
            name=conf.get(CONF_NAME),
        )
        area_coordinator.add_area(area)
    if not area_coordinator.areas:
        return False

    quota_coordinator = LoadSheddingQuotaCoordinator(hass, sepush)
    quota_coordinator.update_interval = timedelta(seconds=QUOTA_UPDATE_INTERVAL)

    hass.data[DOMAIN][config_entry.entry_id] = {
        ATTR_STAGE: stage_coordinator,
        ATTR_AREA: area_coordinator,
        ATTR_QUOTA: quota_coordinator,
    }

    config_entry.async_on_unload(config_entry.add_update_listener(update_listener))

    await stage_coordinator.async_config_entry_first_refresh()
    await area_coordinator.async_config_entry_first_refresh()
    await quota_coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Load Shedding Entry from config_entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Reload config entry."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Update listener."""
    return await hass.config_entries.async_reload(config_entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 3:
        old_data = {**config_entry.data}
        old_options = {**config_entry.options}
        new_data = {}
        new_options = {
            CONF_API_KEY: old_data.get(CONF_API_KEY),
            CONF_AREAS: old_options.get(CONF_AREAS, {}),
        }
        config_entry.version = 4
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options=new_options
        )

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


class LoadSheddingStageCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding Stage."""

    def __init__(self, hass: HomeAssistant, sepush: SePush) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.last_update: datetime | None = None
        self.update_method = self.update_stage

    async def update_stage(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(timezone.utc).replace(microsecond=0)
        diff = 0
        if self.last_update is not None:
            diff = (now - self.last_update).seconds

        if 0 < diff < STAGE_UPDATE_INTERVAL:
            return self.data

        try:
            stage = await self.async_update_stage()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get stage: %s", err, exc_info=True)
            self.data = {}
        else:
            self.data = stage
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
                stage = Stage(int(area.get("stage", "0")))
                start_time = datetime.fromisoformat(area.get("stage_updated"))
                start_time = start_time.replace(second=0, microsecond=0)
                planned = [
                    {
                        ATTR_STAGE: stage,
                        ATTR_START_TIME: start_time.astimezone(timezone.utc),
                    }
                ]

                next_stages = area.get("next_stages", [])
                for i, next_stage in enumerate(next_stages):
                    # Prev
                    prev_end = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    prev_end = prev_end.replace(second=0, microsecond=0)
                    planned[i][ATTR_END_TIME] = prev_end.astimezone(timezone.utc)

                    # Next
                    stage = Stage(int(next_stage.get("stage", "0")))
                    start_time = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    start_time = start_time.replace(second=0, microsecond=0)
                    planned.append(
                        {
                            ATTR_STAGE: stage,
                            ATTR_START_TIME: start_time.astimezone(timezone.utc),
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


class LoadSheddingAreaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding Area."""

    def __init__(
        self,
        hass: HomeAssistant,
        sepush: SePush,
        stage_coordinator: DataUpdateCoordinator,
    ) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.last_update: datetime | None = None
        self.areas: list[Area] = []
        self.stage_coordinator = stage_coordinator
        self.update_method = self.update_area

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def update_area(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(timezone.utc).replace(microsecond=0)
        diff = 0
        if self.last_update is not None:
            diff = (now - self.last_update).seconds

        if 0 < diff < AREA_UPDATE_INTERVAL:
            await self.async_area_forecast()
            return self.data

        try:
            area = await self.async_update_area()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get area schedule: %s", err, exc_info=True)
            self.data = {}
        else:
            self.data = area
            self.last_update = now

        await self.async_area_forecast()
        return self.data

    async def async_update_area(self) -> dict:
        """Retrieve area data."""
        area_id_data: dict = {}

        for area in self.areas:
            try:
                esp = await self.hass.async_add_executor_job(self.sepush.area, area.id)
            except SePushError as err:
                raise UpdateFailed(err) from err

            # Get events for area
            events = []
            for event in esp.get("events", {}):
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
                    min_event_dur = self.stage_coordinator.config_entry.options.get(
                        CONF_MIN_EVENT_DURATION, 30
                    )  # minutes
                    if end_time - start_time < timedelta(minutes=min_event_dur):
                        continue

                    forecast.append(
                        {
                            ATTR_STAGE: planned_stage,
                            ATTR_START_TIME: start_time,
                            ATTR_END_TIME: end_time,
                        }
                    )

            data[ATTR_FORECAST] = forecast


def utc_dt(date: datetime, time: datetime) -> datetime:
    """Given a date and time in SAST, this function returns a datetime object in UTC"""
    sast = timezone(timedelta(hours=+2), "SAST")

    return time.replace(
        year=date.year,
        month=date.month,
        day=date.day,
        second=0,
        microsecond=0,
        tzinfo=sast,
    ).astimezone(timezone.utc)


class LoadSheddingQuotaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding Quota."""

    def __init__(self, hass: HomeAssistant, sepush: SePush) -> None:
        """Initialize."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}")
        self.data = {}
        self.sepush = sepush
        self.last_update: datetime | None = None
        self.update_method = self.update_quota

    async def update_quota(self) -> dict:
        """Retrieve latest load shedding data."""

        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            quota = await self.async_update_quota()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get quota: %s", err, exc_info=True)
        else:
            self.data = quota
            self.last_update = now

        return self.data

    async def async_update_quota(self) -> dict:
        """Retrieve latest quota."""
        try:
            esp = await self.hass.async_add_executor_job(self.sepush.check_allowance)
        except SePushError as err:
            raise UpdateFailed(err) from err

        return esp.get("allowance", {})


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
