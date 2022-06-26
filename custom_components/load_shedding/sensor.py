"""Support for the LoadShedding service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from load_shedding import Stage
from load_shedding.providers import Suburb

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_VIA_DEVICE,
    STATE_ON,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingStageUpdateCoordinator, LoadSheddingScheduleUpdateCoordinator
from .const import (
    ATTR_START_TIME,
    ATTR_END_TIME,
    ATTR_START_IN,
    ATTR_END_IN,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTRIBUTION,
    DOMAIN,
    NAME,
    MAX_FORECAST_DAYS,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinators = hass.data.get(DOMAIN, {})
    stage_coordinator: LoadSheddingStageUpdateCoordinator = coordinators.get(ATTR_STAGE)
    schedule_coordinator: LoadSheddingScheduleUpdateCoordinator = coordinators.get(ATTR_SCHEDULE)

    entities: list[Entity] = []
    suburb = Suburb(
        id=entry.data.get("suburb_id"),
        name=entry.data.get("suburb"),
        municipality=entry.data.get("municipality"),
        province=entry.data.get("province"),
    )
    entities.append(LoadSheddingStageSensorEntity(stage_coordinator))
    entities.append(LoadSheddingScheduleSensorEntity(schedule_coordinator, suburb))

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""
    pass


class LoadSheddingStageSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Stage entity."""
    coordinator: LoadSheddingStageUpdateCoordinator

    def __init__(self, coordinator: LoadSheddingStageUpdateCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator)

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        self._device_id = "loadshedding.eskom.co.za"
        self._state: StateType = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._attr_name = f"{NAME} Stage"
        self._attr_unique_id = description.key

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if self.coordinator.data:
            stage = self.coordinator.data.get(ATTR_STAGE)
            self._state = cast(StateType, str(stage))
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: self.coordinator.provider.__class__.__name__,
            ATTR_MODEL: "API",
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return self._attrs
        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self.async_write_ha_state()


class LoadSheddingScheduleSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Schedule entity."""
    coordinator: LoadSheddingScheduleUpdateCoordinator

    def __init__(self, coordinator: LoadSheddingScheduleUpdateCoordinator, suburb: Suburb) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.suburb = suburb

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {suburb.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} schedule {suburb.name}",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        self._device_id = "loadshedding.eskom.co.za"
        self._state: StateType = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._attr_name = f"{NAME} {suburb.name}"
        self._attr_unique_id = description.key
        self.schedule = []

        suburb_data = self.coordinator.data.get(self.suburb.id, {})
        schedule = suburb_data.get(ATTR_SCHEDULE, {})

        if not schedule:
            return self._attrs

        now = datetime.now(timezone.utc)
        days = MAX_FORECAST_DAYS
        for s in schedule:
            start_time = datetime.fromisoformat(s[0])
            end_time = datetime.fromisoformat(s[1])

            if start_time > now + timedelta(days=days):
                continue

            if end_time < now:
                continue

            self.schedule.append({
                ATTR_START_TIME: str(start_time.isoformat()),
                ATTR_END_TIME: str(end_time.isoformat()),
            })

    @property
    def native_value(self) -> StateType:
        """Return the schedule state."""
        now = datetime.now(timezone.utc)
        if self.coordinator.data:
            stage = self.coordinator.data.get(ATTR_STAGE)
            if stage in [Stage.UNKNOWN, Stage.NO_LOAD_SHEDDING]:
                self._state = cast(StateType, STATE_OFF)
                return self._state

        if self.schedule:
            self._state = cast(StateType, STATE_OFF)
            start_time = datetime.fromisoformat(self.schedule[0].get(ATTR_START_TIME))
            end_time = datetime.fromisoformat(self.schedule[0].get(ATTR_END_TIME))
            if start_time < now < end_time:
                self._state = cast(StateType, STATE_ON)
                return self._state

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: self.coordinator.provider.__class__.__name__,
            ATTR_MODEL: "API",
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return self._attrs

        now = datetime.now(timezone.utc)
        starts_in = ends_in = None
        for s in self.schedule:
            if not ends_in:
                ends_at = datetime.fromisoformat(s.get(ATTR_END_TIME))
                ends_in = ends_at - now
                ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)

            starts_at = datetime.fromisoformat(s.get(ATTR_START_TIME))
            starts_in = starts_at - now
            starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)

            if starts_in.total_seconds() > 0:
                break

        self._attrs.update(
            {
                ATTR_START_TIME: self.schedule[0].get(ATTR_START_TIME),
                ATTR_END_TIME: self.schedule[0].get(ATTR_END_TIME),
                ATTR_START_IN: starts_in.total_seconds(),
                ATTR_END_IN: ends_in.total_seconds(),
                ATTR_SCHEDULE: self.schedule,
            }
        )

        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self.async_write_ha_state()
