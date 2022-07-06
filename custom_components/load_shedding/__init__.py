"""The LoadShedding component."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, Config
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from load_shedding import (
    Provider,
    StageError,
    Stage,
    get_stage,
    get_schedule,
    get_providers,
)
from load_shedding.providers import ProviderError, Suburb
from .const import (
    ATTR_SCHEDULE,
    ATTR_SCHEDULES,
    ATTR_STAGE,
    ATTR_START_TIME,
    ATTR_END_TIME,
    CONF_MUNICIPALITY,
    CONF_PROVIDER,
    CONF_PROVINCE,
    CONF_STAGE,
    CONF_SUBURB,
    CONF_SUBURB_ID,
    CONF_SUBURBS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STAGE,
    DOMAIN,
    MAX_FORECAST_DAYS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""
    provider = load_provider(entry.data.get(CONF_STAGE, {}).get(CONF_PROVIDER))
    stage_coordinator = LoadSheddingStageUpdateCoordinator(hass, provider)

    schedule_coordinator = LoadSheddingScheduleUpdateCoordinator(hass, provider)
    for suburb_conf in entry.data.get(CONF_SUBURBS, {}):
        suburb = Suburb(
            id=suburb_conf.get(CONF_SUBURB_ID),
            name=suburb_conf.get(CONF_SUBURB),
            municipality=suburb_conf.get(CONF_MUNICIPALITY),
            province=suburb_conf.get(CONF_PROVINCE),
        )
        schedule_coordinator.add_suburb(suburb)

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


class LoadSheddingStageUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching LoadShedding stage from Provider."""

    def __init__(self, hass: HomeAssistant, provider: Provider) -> None:
        """Initialize."""
        self.hass = hass
        # TODO: Make providers selectable from config flow once more are available.
        self.provider = provider
        self.name = f"{DOMAIN}_{ATTR_STAGE}"
        super().__init__(
            self.hass, _LOGGER, name=self.name, update_method=self.async_update_stage
        )

    async def async_update_stage(self) -> None:
        """Retrieve latest stage."""
        try:
            stage = await self.hass.async_add_executor_job(
                get_stage,
                self.provider,
            )
        except (ProviderError, StageError, Exception) as e:
            _LOGGER.error("Unable to get stage", exc_info=True)
            return self.data
        else:
            if stage in [Stage.UNKNOWN]:
                return self.data

            return {**{ATTR_STAGE: stage}}


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching LoadShedding schedule from Provider."""

    def __init__(self, hass: HomeAssistant, provider: Provider) -> None:
        """Initialize."""
        self.hass = hass
        self.provider = provider
        self.suburbs: list[Suburb] = []
        self.name = f"{DOMAIN}_{ATTR_SCHEDULE}"
        super().__init__(
            self.hass, _LOGGER, name=self.name, update_method=self.async_update_schedule
        )

    def add_suburb(self, suburb: Suburb = None) -> None:
        """Add a suburb to update."""
        self.suburbs.append(suburb)

    async def async_update_schedule(self) -> None:
        """Retrieve schedule data."""
        stage: Stage = None
        stage_coordinator: LoadSheddingStageUpdateCoordinator = self.hass.data.get(
            DOMAIN, {}
        ).get(ATTR_STAGE)
        if stage_coordinator.data:
            stage = Stage(stage_coordinator.data.get(ATTR_STAGE))

        forecast_stage = stage
        if forecast_stage in [Stage.NO_LOAD_SHEDDING]:
            forecast_stage = DEFAULT_STAGE

        schedules = {}
        for suburb in self.suburbs:
            try:
                schedules[suburb.id] = {}
                data = await self.async_get_suburb_data(suburb, forecast_stage)
            except UpdateFailed as e:
                _LOGGER.error(f"Unable to get suburb data", exc_info=True)
                continue
            else:
                schedules[suburb.id] = data

        return {**{ATTR_STAGE: stage, ATTR_SCHEDULES: schedules}}

    async def async_get_suburb_data(self, suburb: Suburb, stage: Stage = None) -> Dict:
        """Retrieve schedule for given suburb and stage."""
        try:
            schedule = await self.hass.async_add_executor_job(
                get_schedule,
                self.provider,
                suburb.province,
                suburb,
                stage,
            )
        except (ProviderError, StageError) as e:
            _LOGGER.error(f"Unknown error", exc_info=True)
            raise UpdateFailed(f"unable to get schedule")
        except Exception as e:
            _LOGGER.error(f"Unknown error", exc_info=True)
            raise UpdateFailed(f"unable to get schedule")
        else:
            data = []
            now = datetime.now(timezone.utc)
            for s in schedule:
                start_time = datetime.fromisoformat(s[0])
                end_time = datetime.fromisoformat(s[1])

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


def load_provider(name: str) -> Provider:
    providers = get_providers()
    for p in providers:
        if f"{p.__class__.__module__}.{p.__class__.__name__}" == name:
            return p

    return Exception(f"No provider found: {name}")
