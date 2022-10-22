"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import timedelta, datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_NAME,
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    CONF_DESCRIPTION,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from load_shedding import (
    Provider,
)
from load_shedding.libs.sepush import SePush, SePushError
from load_shedding.providers import (
    Area,
    Province,
    Stage,
    to_utc,
)
from .const import (
    API_UPDATE_INTERVAL,
    ATTR_AREAS,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_STAGE_FORECAST,
    CONF_COCT,
    CONF_ESKOM,
    CONF_MUNICIPALITY,
    CONF_PROVINCE_ID,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ATTR_FORECAST,
    ATTR_START_TIME,
    ATTR_END_TIME,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    api_key = entry.data.get(CONF_API_KEY)
    provider: SePush = SePush(token=api_key)
    stage_coordinator = LoadSheddingStageUpdateCoordinator(hass, provider)

    schedule_coordinator = LoadSheddingScheduleUpdateCoordinator(hass, provider)
    for data in entry.data.get(CONF_AREAS, []):
        area = Area(
            id=data.get(CONF_AREA_ID),
            name=data.get(CONF_AREA),
            municipality=data.get(CONF_MUNICIPALITY),
            province=Province(data.get(CONF_PROVINCE_ID)),
        )
        schedule_coordinator.add_area(area)

    quota_coordinator = LoadSheddingQuotaUpdateCoordinator(hass, provider)

    hass.data[DOMAIN] = {
        ATTR_STAGE: stage_coordinator,
        ATTR_SCHEDULE: schedule_coordinator,
        ATTR_QUOTA: quota_coordinator,
    }

    await stage_coordinator.async_config_entry_first_refresh()
    await schedule_coordinator.async_config_entry_first_refresh()
    await quota_coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))

    async def _schedule_updates(*_):
        """Activate the data update coordinators."""
        stage_coordinator.update_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        await stage_coordinator.async_refresh()

        schedule_coordinator.update_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        await schedule_coordinator.async_refresh()

        quota_coordinator.update_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        await quota_coordinator.async_refresh()

    if hass.state == CoreState.running:
        await _schedule_updates()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_updates)

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Load Shedding Entry from config_entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


class LoadSheddingStageUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding stage from Provider."""

    def __init__(self, hass: HomeAssistant, provider: SePush) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ATTR_STAGE}",
            update_method=self.async_update_stage,
        )
        self.data = {}
        self.provider = provider
        self.last_updated: datetime = None

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        now = datetime.now()
        if (
            self.last_updated is not None
            and (now - self.last_updated).seconds < API_UPDATE_INTERVAL
        ):
            return self.data

        try:
            esp = await self.hass.async_add_executor_job(self.provider.status)
        except (SePushError) as err:
            raise UpdateFailed(err) from err
            # _LOGGER.debug("Unable to get stage %s", err, exc_info=True)
            # return self.data

        sources = esp.get("status", {})
        for source in sources:
            key = CONF_ESKOM
            if source == "capetown":
                key = CONF_COCT

            data = sources.get(source)

            stage_forecast = [
                {
                    ATTR_STAGE: Stage(int(data.get("stage", "0"))),
                    ATTR_START_TIME: datetime.fromisoformat(
                        data.get("stage_updated")
                    ).astimezone(timezone.utc),
                }
            ]
            for next_stage in data.get("next_stages", []):
                stage_forecast.append(
                    {
                        ATTR_STAGE: Stage(int(next_stage.get("stage", "0"))),
                        ATTR_START_TIME: datetime.fromisoformat(
                            next_stage.get("stage_start_timestamp")
                        ).astimezone(timezone.utc),
                    }
                )

            for i, forecast in enumerate(stage_forecast):
                if i < len(stage_forecast) - 1:
                    stage_forecast[i][ATTR_END_TIME] = stage_forecast[i + 1][
                        ATTR_START_TIME
                    ]

            self.data[key] = {
                ATTR_NAME: data.get("name", ""),
                ATTR_STAGE: Stage(int(data.get("stage", "0"))),
                ATTR_STAGE_FORECAST: stage_forecast,
            }

        self.last_updated = now
        return self.data


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding schedule from Provider."""

    def __init__(self, hass: HomeAssistant, provider: SePush) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ATTR_SCHEDULE}",
            update_method=self.async_update_schedule,
        )
        self.data = {}
        self.provider = provider
        self.last_updated: datetime = None
        self.areas: list[Area] = []

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def async_update_schedule(self) -> dict:
        """Retrieve schedule data."""
        now = datetime.now()
        if (
            self.last_updated is not None
            and (now - self.last_updated).seconds < API_UPDATE_INTERVAL
        ):
            return self.data

        areas: dict = {}
        for area in self.areas:
            # Get foreacast for area
            forecast = []
            try:
                data = await self.hass.async_add_executor_job(
                    self.provider.area, area.id
                )
            except (SePushError) as err:
                raise UpdateFailed(err) from err

            for event in data.get("events", {}):
                note = event.get("note")
                parts = str(note).split(" ")
                stage = Stage(int(parts[1]))
                start = datetime.fromisoformat(event.get("start")).astimezone(
                    timezone.utc
                )
                end = datetime.fromisoformat(event.get("end")).astimezone(timezone.utc)

                forecast.append(
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
                stages = day.get("stages", [])
                for i, stage in enumerate(stages):
                    schedule = []
                    for slot in stages[i]:
                        start_str, end_str = slot.strip().split("-")
                        start = datetime.strptime(start_str, "%H:%M").replace(
                            year=date.year,
                            month=date.month,
                            day=date.day,
                            second=0,
                            microsecond=0,
                            tzinfo=sast,
                        )
                        end = datetime.strptime(end_str, "%H:%M").replace(
                            year=date.year,
                            month=date.month,
                            day=date.day,
                            second=0,
                            microsecond=0,
                            tzinfo=sast,
                        )
                        if end < start:
                            end = end + timedelta(days=1)
                        schedule.append((start, end))

                    schedule = to_utc(schedule)
                    stage_schedule[i + 1] = schedule

            areas[area.id] = {
                ATTR_FORECAST: forecast,
                ATTR_SCHEDULE: stage_schedule,
            }

        self.data[ATTR_AREAS] = areas
        self.last_updated = now
        return self.data


class LoadSheddingQuotaUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to check Provider quota."""

    def __init__(self, hass: HomeAssistant, provider: SePush) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ATTR_QUOTA}",
            update_method=self.async_update_quota,
        )
        self.data = {}
        self.provider = provider
        self.last_updated: datetime = None

    async def async_update_quota(self) -> dict:
        """Retrieve latest Quota."""
        now = datetime.now()
        if (
            self.last_updated is not None
            and (now - self.last_updated).seconds < API_UPDATE_INTERVAL
        ):
            return self.data

        try:
            esp = await self.hass.async_add_executor_job(self.provider.check_allowance)
        except (SePushError) as err:
            raise UpdateFailed(err) from err
            # _LOGGER.debug("Unable to get Quota %s", err, exc_info=True)
            # return self.data

        self.data = esp.get("allowance", {})
        self.last_updated = now
        return self.data
