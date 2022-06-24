"""The LoadShedding component."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any, Dict

from load_shedding import ScheduleError, Stage, get_schedule
from load_shedding.providers import ProviderError, Suburb

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, Config
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ATTR_SCHEDULE, ATTR_SCHEDULES, ATTR_STAGE, STAGE_SCAN_INTERVAL, SCHEDULE_SCAN_INTERVAL, DEFAULT_STAGE, DOMAIN, PROVIDER

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: Config):
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoadShedding as config entry."""

    suburb = Suburb(
        id=entry.data.get("suburb_id"),
        name=entry.data.get("suburb"),
        municipality=entry.data.get("municipality"),
        province=entry.data.get("province"),
    )

    stage_coordinator = LoadSheddingStageUpdateCoordinator(hass)
    await stage_coordinator.async_config_entry_first_refresh()

    schedule_coordinator = LoadSheddingScheduleUpdateCoordinator(hass)
    schedule_coordinator.add_suburb(suburb)
    await schedule_coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))

    async def _schedule_updates(*_):
        """Activate the data update schedule_coordinator."""
        stage_coordinator.update_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, STAGE_SCAN_INTERVAL)
        )
        await stage_coordinator.async_refresh()

        schedule_coordinator.update_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, SCHEDULE_SCAN_INTERVAL)
        )
        await schedule_coordinator.async_refresh()

    if hass.state == CoreState.running:
        await _schedule_updates()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_updates)

    hass.data[DOMAIN+ATTR_STAGE] = stage_coordinator
    hass.data[DOMAIN+ATTR_SCHEDULE] = schedule_coordinator

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

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.provider = PROVIDER()
        super().__init__(
            self.hass, _LOGGER, name=DOMAIN, update_method=self.async_update_stage
        )

    async def async_update_stage(self) -> None:
        """Retrieve latest stage."""
        try:
            stage = await self.hass.async_add_executor_job(self.provider.get_stage)
        except ProviderError as e:
            raise UpdateFailed(f"{e}")

        if stage in [Stage.UNKNOWN]:
            raise UpdateFailed("Unknown stage")

        return {**{ATTR_STAGE: stage}}


class LoadSheddingScheduleUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching LoadShedding data from Provider."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.provider = PROVIDER()
        self.suburbs: list[Suburb] = []
        super().__init__(
            self.hass, _LOGGER, name=DOMAIN, update_method=self.async_update_schedule_data
        )

    def add_suburb(self, suburb: Suburb = None) -> None:
        """Add a suburb to update."""
        self.suburbs.append(suburb)

    async def async_update_schedule_data(self) -> None:
        """Retrieve schedule data."""
        stage: Stage = None
        stage_coordinator: LoadSheddingStageUpdateCoordinator = self.hass.data[DOMAIN+ATTR_STAGE]
        if stage_coordinator.data:
            stage = Stage(stage_coordinator.data.get(ATTR_STAGE))

        if stage in [Stage.NO_LOAD_SHEDDING]:
            stage = DEFAULT_STAGE

        schedules = {}
        for suburb in self.suburbs:
            try:
                schedules[suburb.id] = {}
                schedule = await self.async_get_suburb_schedule(suburb, stage)
            except (ProviderError, ScheduleError) as e:
                _LOGGER.error(f"unable to get schedule for suburb: {suburb} {stage} {e}")
                continue
            else:
                schedules[suburb.id] = schedule

        return schedules

    async def async_get_suburb_schedule(self, suburb: Suburb, stage: Stage = None) -> Dict:
        """Retrieve schedule for given suburb and stage."""
        try:
            schedule = await self.hass.async_add_executor_job(
                get_schedule,
                self.provider,
                suburb.province,
                suburb,
                stage,
            )
        except (ProviderError, ScheduleError) as e:
            raise UpdateFailed(f"{e}")

        return {**{ATTR_STAGE: stage, ATTR_SCHEDULE: schedule}}
