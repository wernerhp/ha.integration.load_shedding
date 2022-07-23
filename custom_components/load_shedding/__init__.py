"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import timedelta, datetime, timezone
from typing import Any

from regex import B

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    CONF_DESCRIPTION,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from load_shedding import (
    get_area_schedule,
    get_stage,
    get_stage_forecast,
    get_area_forecast,
    Provider,
)
from load_shedding.providers import Area, Province, ProviderError, StageError, Stage
from .const import (
    ATTR_SCHEDULE,
    ATTR_STAGE,
    CONF_DEFAULT_SCHEDULE_STAGE,
    CONF_MUNICIPALITY,
    CONF_PROVIDER,
    CONF_PROVINCE_ID,
    CONF_STAGE,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ATTR_STAGE_FORECAST,
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
    provider = Provider(stage_data.get(CONF_PROVIDER))()
    default_stage = Stage(stage_data.get(CONF_DEFAULT_SCHEDULE_STAGE, 4))
    stage_coordinator = LoadSheddingStageUpdateCoordinator(hass, provider)

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
        await schedule_coordinator.async_refresh()

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

    def __init__(self, hass: HomeAssistant, provider: Provider) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ATTR_STAGE}",
            update_method=self.async_update_stage,
        )
        self.data = {}
        self.provider = provider
        self.stage_forecast: list = []

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        # Current Stage
        try:
            current_stage = await self.hass.async_add_executor_job(
                get_stage, self.provider
            )
        except (ProviderError, StageError) as err:
            _LOGGER.debug("Unable to get stage %s", err, exc_info=True)
            return self.data
        else:
            self.data[ATTR_STAGE] = current_stage

        # Forecast Stage
        try:
            stage_forecast = await self.hass.async_add_executor_job(
                get_stage_forecast, self.provider
            )
        except (ProviderError, StageError) as err:
            _LOGGER.debug("Unable to get stage forecast %s", err, exc_info=True)
            return self.data
        else:
            self.stage_forecast = stage_forecast
            self.data[ATTR_STAGE_FORECAST] = stage_forecast

        return self.data


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding schedule from Provider."""

    def __init__(
        self, hass: HomeAssistant, provider: Provider, default_stage: Stage
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
        stage_coordinator: LoadSheddingStageUpdateCoordinator = self.hass.data.get(
            DOMAIN, {}
        ).get(ATTR_STAGE)

        current_stage: Stage = Stage.UNKNOWN
        if stage_coordinator.data:
            current_stage = stage_coordinator.data.get(ATTR_STAGE)
            stage_forecast = stage_coordinator.data.get(ATTR_STAGE_FORECAST, [])

        if current_stage in [Stage.UNKNOWN]:
            return self.data

        area_forecasts: dict = {}
        area_schedules: dict = {}
        for area in self.areas:
            area_forecasts[area.id] = []
            area_schedules[area.id] = []

            # Get area forecast for each forecast stage
            for forecast in stage_forecast:
                try:
                    area_forecast = await self.get_area_forecast(area, forecast)
                except ProviderError:
                    continue
                else:
                    area_forecasts[area.id].extend(area_forecast)

            if not area_forecasts[area.id] and current_stage not in [
                Stage.NO_LOAD_SHEDDING
            ]:
                # Get area schedule for current stage
                try:
                    now = datetime.now(timezone.utc)
                    forecast = {
                        ATTR_STAGE: current_stage,
                        ATTR_START_TIME: now,
                        ATTR_END_TIME: now + timedelta(days=7),
                    }
                    area_forecast = await self.get_area_forecast(area, forecast)
                except ProviderError:
                    continue
                else:
                    area_forecasts[area.id].extend(area_forecast)

            # Get area schedule for default stage
            try:
                now = datetime.now(timezone.utc).replace(
                    minute=0, second=0, microsecond=0
                )
                forecast = {
                    ATTR_STAGE: self.default_stage,
                    ATTR_START_TIME: now,
                    ATTR_END_TIME: now.replace(hour=0)
                    + timedelta(days=MAX_FORECAST_DAYS),
                }
                area_schedule = await self.get_area_forecast(area, forecast)
            except ProviderError:
                continue
            else:
                area_schedules[area.id].extend(area_schedule)

        self.data[ATTR_FORECAST] = area_forecasts
        self.data[ATTR_SCHEDULE] = area_schedules

        return self.data

    async def get_area_forecast(self, area, forecast):
        """Get the forecast for an area"""
        forecast_stage = forecast.get(ATTR_STAGE)
        if forecast_stage in [Stage.NO_LOAD_SHEDDING, Stage.UNKNOWN]:
            raise ProviderError
        try:
            # Get area schedule for the forecast stage
            area_schedule = await self.hass.async_add_executor_job(
                get_area_schedule, self.provider, area, forecast_stage
            )
        except (StageError, Exception) as err:
            _LOGGER.debug("Unable to get area schedule: %s", err, exc_info=True)
            raise ProviderError from err

        try:
            # Get area forecast from area schedule and stage forecast
            area_forecast = await self.hass.async_add_executor_job(
                get_area_forecast, area_schedule, forecast
            )
        except Exception as err:
            _LOGGER.debug("Unable to get area forecast: %s", err, exc_info=True)
            raise ProviderError from err
        else:
            return area_forecast


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
