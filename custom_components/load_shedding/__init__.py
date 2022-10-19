"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import timedelta, datetime, timezone
from typing import Any
from flask import current_app

from regex import B

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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from load_shedding import (
    # get_area_schedule,
    # get_stages,
    # get_stage_forecast,
    # get_area_forecast,
    Provider,
)
from load_shedding.libs.sepush import SePush
from load_shedding.providers import (
    Area,
    Province,
    ProviderError,
    StageError,
    Stage,
    to_utc,
)
from .const import (
    ATTR_AREAS,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_STAGE_FORECAST,
    CONF_COCT,
    CONF_ESKOM,
    CONF_DEFAULT_SCHEDULE_STAGE,
    CONF_MUNICIPALITY,
    CONF_PROVIDER,
    CONF_PROVINCE_ID,
    CONF_STAGE,
    CONF_STAGE_COCT,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    # ATTR_STAGE_FORECAST,
    ATTR_FORECAST,
    ATTR_START_TIME,
    ATTR_END_TIME,
    MAX_FORECAST_DAYS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    stage_data = entry.data.get(CONF_STAGE, {})
    # provider = Provider(stage_data.get(CONF_PROVIDER))()
    api_key = entry.data.get(CONF_API_KEY)
    # provider = Provider.SE_PUSH(token=api_key)
    provider: SePush = SePush(token=api_key)
    default_stage = Stage(stage_data.get(CONF_DEFAULT_SCHEDULE_STAGE, 4))
    # coct_stage = entry.data.get(CONF_STAGE_COCT, False)
    stage_coordinator = LoadSheddingStageUpdateCoordinator(
        hass, provider
    )  # , coct_stage)

    schedule_coordinator = LoadSheddingScheduleUpdateCoordinator(
        hass, provider, default_stage=default_stage
    )
    for data in entry.data.get(CONF_AREAS, []):
        area = Area(
            id=data.get(CONF_AREA_ID),
            name=data.get(CONF_AREA),
            municipality=data.get(CONF_MUNICIPALITY),
            province=Province(data.get(CONF_PROVINCE_ID)),
        )
        schedule_coordinator.add_area(area)

    hass.data[DOMAIN] = {
        ATTR_STAGE: stage_coordinator,
        ATTR_SCHEDULE: schedule_coordinator,
    }

    await stage_coordinator.async_config_entry_first_refresh()
    await schedule_coordinator.async_config_entry_first_refresh()

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
        # await schedule_coordinator.async_refresh()

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

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        try:
            esp = await self.hass.async_add_executor_job(self.provider.status)
        except (ProviderError, StageError, Exception) as err:
            _LOGGER.debug("Unable to get stage %s", err, exc_info=True)
            return self.data

        sources = esp.get("status", {})
        for source in sources:
            key = CONF_ESKOM
            if source == "capetown":
                key = CONF_COCT

            data = sources.get(source)

            stage_forecast = []
            for next_stage in data.get("next_stages", []):
                stage_forecast.append(
                    {
                        ATTR_STAGE: Stage(int(next_stage.get("stage", "0"))),
                        ATTR_START_TIME: datetime.fromisoformat(
                            next_stage.get("stage_start_timestamp")
                        ).astimezone(timezone.utc),
                        ATTR_END_TIME: datetime.fromisoformat(
                            next_stage.get("stage_start_timestamp")
                        )
                        .replace(hour=23, minute=59, second=59, microsecond=9999)
                        .astimezone(timezone.utc),
                    }
                )

            self.data[key] = {
                ATTR_NAME: data.get("name", ""),
                ATTR_STAGE: Stage(int(data.get("stage", "0"))),
                ATTR_STAGE_FORECAST: stage_forecast,
            }

        return self.data


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding schedule from Provider."""

    def __init__(
        self, hass: HomeAssistant, provider: SePush, default_stage: Stage
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ATTR_SCHEDULE}",
            update_method=self.async_update_schedule,
        )
        self.data = {}
        self.provider = provider
        self.default_stage = default_stage
        self.areas: list[Area] = []

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def async_update_schedule(self) -> dict:
        """Retrieve schedule data."""

        areas: dict = {}
        for area in self.areas:
            # Get foreacast for area
            forecast = []
            try:
                data = await self.hass.async_add_executor_job(
                    self.provider.area, area.id
                )
            except Exception as e:
                raise ProviderError(e)

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
                # if len(stages) < stage.value:
                #     continue
                for stage in range(len(stages)):
                    schedule = []
                    for slot in stages[stage]:
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
                    stage_schedule[stage + 1] = schedule

            areas[area.id] = {
                ATTR_FORECAST: forecast,
                ATTR_SCHEDULE: stage_schedule,
            }

        # self.data[ATTR_FORECAST] = area_forecasts
        self.data[ATTR_AREAS] = areas

        return self.data

    # async def get_area_forecast(self, area, forecast):
    #     """Get the forecast for an area"""
    #     forecast_stage = forecast.get(ATTR_STAGE)
    #     if forecast_stage in [Stage.NO_LOAD_SHEDDING, Stage.UNKNOWN]:
    #         raise ProviderError
    #     try:
    #         # Get area schedule for the forecast stage
    #         area_schedule = await self.hass.async_add_executor_job(
    #             get_area_schedule, self.provider, area, forecast_stage
    #         )
    #     except (StageError, Exception) as err:
    #         _LOGGER.debug("Unable to get area schedule: %s", err, exc_info=True)
    #         raise ProviderError from err

    #     try:
    #         # Get area forecast from area schedule and stage forecast
    #         area_forecast = await self.hass.async_add_executor_job(
    #             get_area_forecast, area_schedule, forecast
    #         )
    #     except Exception as err:
    #         _LOGGER.debug("Unable to get area forecast: %s", err, exc_info=True)
    #         raise ProviderError from err
    #     else:
    #         return area_forecast


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        old = {**config_entry.data}
        suburbs = old.get("suburbs")
        new = {
            CONF_STAGE: {
                CONF_PROVIDER: Provider.ESKOM.value,
            },
            CONF_AREAS: [
                {
                    CONF_DESCRIPTION: suburbs[0].get(CONF_DESCRIPTION),
                    CONF_AREA: suburbs[0].get("suburb"),
                    CONF_AREA_ID: suburbs[0].get("suburb_id"),
                    CONF_PROVIDER: Provider.ESKOM.value,
                    CONF_PROVINCE_ID: suburbs[0].get(CONF_PROVINCE_ID),
                }
            ],
        }
        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True
