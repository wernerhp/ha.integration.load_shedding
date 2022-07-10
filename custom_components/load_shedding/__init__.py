"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_STARTED, CONF_DESCRIPTION
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.exceptions import IntegrationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from load_shedding import get_schedule, get_stage, Provider
from load_shedding.providers import Area, Province, ProviderError, StageError, Stage
from .const import (
    ATTR_SCHEDULE,
    ATTR_SCHEDULES,
    ATTR_STAGE,
    ATTR_START_TIME,
    ATTR_END_TIME,
    CONF_MUNICIPALITY,
    CONF_PROVIDER,
    CONF_PROVINCE,
    CONF_PROVINCE_ID,
    CONF_STAGE,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STAGE,
    DOMAIN,
    MAX_FORECAST_DAYS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this integration using YAML is not supported."""
    return True


async def async_migrate_entry(hass, config_entry: ConfigEntry):
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
                    CONF_DESCRIPTION: suburbs.get(CONF_DESCRIPTION),
                    CONF_AREA: suburbs.get("suburb"),
                    CONF_AREA_ID: suburbs.get("suburb_id"),
                    CONF_PROVIDER: Provider.ESKOM.value,
                    CONF_PROVINCE_ID: suburbs.get(CONF_PROVINCE_ID),
                }
            ],
        }
        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=new)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    provider = Provider(entry.data.get(CONF_STAGE, {}).get(CONF_PROVIDER))()
    stage_coordinator = LoadSheddingStageUpdateCoordinator(hass, provider)

    schedule_coordinator = LoadSheddingScheduleUpdateCoordinator(hass, provider)
    for data in entry.data.get(CONF_AREAS, {}):
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
        self.hass = hass

        self.provider = provider
        self.name = f"{DOMAIN}_{ATTR_STAGE}"
        super().__init__(
            self.hass, _LOGGER, name=self.name, update_method=self.async_update_stage
        )

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        try:
            stage = await self.hass.async_add_executor_job(
                get_stage,
                self.provider,
            )
        except (ProviderError, StageError) as err:
            _LOGGER.debug("Unable to get stage %s", err, exc_info=True)
            return self.data
        except Exception as err:
            _LOGGER.debug("Unknown error: %s", err, exc_info=True)
            return self.data
        else:
            if stage in [Stage.UNKNOWN]:
                return self.data

            return {**{ATTR_STAGE: stage}}


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding schedule from Provider."""

    def __init__(self, hass: HomeAssistant, provider: Provider) -> None:
        """Initialize."""
        self.hass = hass
        self.provider = provider
        self.areas: list[Area] = []
        self.name = f"{DOMAIN}_{ATTR_SCHEDULE}"
        super().__init__(
            self.hass, _LOGGER, name=self.name, update_method=self.async_update_schedule
        )

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def async_update_schedule(self) -> dict:
        """Retrieve schedule data."""
        stage: Stage = Stage.UNKNOWN
        stage_coordinator: LoadSheddingStageUpdateCoordinator = self.hass.data.get(
            DOMAIN, {}
        ).get(ATTR_STAGE)
        if stage_coordinator.data:
            stage = Stage(stage_coordinator.data.get(ATTR_STAGE))

        forecast_stage = stage
        if forecast_stage in [Stage.NO_LOAD_SHEDDING]:
            forecast_stage = DEFAULT_STAGE

        schedules = {}
        for area in self.areas:
            try:
                schedules[area.id] = {}
                data = await self.async_get_area_data(area, forecast_stage)
            except UpdateFailed as err:
                _LOGGER.debug("Unable to get area data: %s", err, exc_info=True)
                continue
            else:
                schedules[area.id] = data

        return {**{ATTR_STAGE: stage, ATTR_SCHEDULES: schedules}}

    async def async_get_area_data(self, area: Area, stage: Stage = None) -> dict:
        """Retrieve schedule for given area and stage."""
        try:
            schedule = await self.hass.async_add_executor_job(
                get_schedule,
                self.provider,
                area,
                stage,
            )
        except (ProviderError, StageError) as err:
            _LOGGER.debug("Unknown error: %s", err, exc_info=True)
            raise UpdateFailed("Unable to get schedule") from err
        except Exception as err:
            _LOGGER.debug("Unknown error: %s", err, exc_info=True)
            raise UpdateFailed("Unable to get schedule") from err
        else:
            data = []
            now = datetime.now(timezone.utc)
            for s in schedule:
                start_time = s[0]
                end_time = s[1]

                if start_time > now + timedelta(days=MAX_FORECAST_DAYS):
                    continue

                if end_time < now:
                    continue

                data.append(
                    {
                        ATTR_START_TIME: str(start_time.isoformat()),
                        ATTR_END_TIME: str(end_time.isoformat()),
                    }
                )

            return {**{ATTR_STAGE: stage, ATTR_SCHEDULE: data}}
