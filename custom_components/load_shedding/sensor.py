"""Support for the LoadShedding service."""
from __future__ import annotations
import logging

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from load_shedding import Provider, Stage
from load_shedding.providers import Area, Province

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
    API,
    ATTR_AREAS,
    ATTR_START_TIME,
    ATTR_END_TIME,
    ATTR_START_IN,
    ATTR_END_IN,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_NEXT_END_TIME,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTRIBUTION,
    CONF_MUNICIPALITY,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    DOMAIN,
    NAME,
    MANUFACTURER,
    MAX_FORECAST_DAYS,
    CONF_PROVINCE_ID,
    ATTR_FORECAST,
    ATTR_STAGE_FORECAST,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinators = hass.data.get(DOMAIN, {})
    entities: list[Entity] = []

    stage_coordinator: LoadSheddingStageUpdateCoordinator = coordinators.get(ATTR_STAGE)
    for data in stage_coordinator.data:
        stage_entity = LoadSheddingStageSensorEntity(stage_coordinator, data)
        entities.append(stage_entity)

    schedule_coordinator: LoadSheddingScheduleUpdateCoordinator = coordinators.get(
        ATTR_SCHEDULE
    )

    for data in entry.data.get(CONF_AREAS, {}):
        area = Area(
            id=data.get(CONF_AREA_ID),
            name=data.get(CONF_AREA),
            municipality=data.get(CONF_MUNICIPALITY),
            province=Province(data.get(CONF_PROVINCE_ID)),
        )
        area_entity = LoadSheddingScheduleSensorEntity(schedule_coordinator, area)
        entities.append(area_entity)

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""


class LoadSheddingStageSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Stage entity."""

    coordinator: LoadSheddingStageUpdateCoordinator

    def __init__(
        self, coordinator: LoadSheddingStageUpdateCoordinator, source: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        self.data = coordinator.data.get(source)
        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )

        # self.provider: Provider = provider
        # self.source = source
        self.entity_description = description
        # self._device_id = "loadshedding.eskom.co.za"
        self._device_id = f"{NAME}"
        self._state: StateType = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION.format(provider="sepush.co.za")}
        name = self.data.get("name", "")
        self._attr_name = f"{NAME} {name} Stage"
        self._attr_unique_id = f"stage_{name}"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if self.data:
            stage = self.data.get(ATTR_STAGE, Stage.UNKNOWN)
            if stage in [Stage.UNKNOWN]:
                return self._state
            self._state = cast(StateType, stage)
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.data:
            return self._attrs

        stage = self.data.get(ATTR_STAGE, Stage.UNKNOWN)
        if stage in [Stage.UNKNOWN]:
            return self._attrs

        stage_forecast = self.data.get(ATTR_STAGE_FORECAST, [])

        data = get_sensor_attrs(stage_forecast, stage)
        for f in stage_forecast:
            forecast = {
                ATTR_STAGE: f.get(ATTR_STAGE).value,
                ATTR_START_TIME: f.get(ATTR_START_TIME).isoformat(),
            }
            if ATTR_END_TIME in f:
                forecast[ATTR_END_TIME] = f.get(ATTR_END_TIME).isoformat()

            data[ATTR_FORECAST].append(forecast)
        self._attrs.update(data)

        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self.async_write_ha_state()


class LoadSheddingScheduleSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Schedule entity."""

    coordinator: LoadSheddingScheduleUpdateCoordinator

    def __init__(
        self, coordinator: LoadSheddingScheduleUpdateCoordinator, area: Area
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.area = area

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {area.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} schedule {area.name}",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        # self._device_id = "loadshedding.eskom.co.za"
        self._device_id = f"{NAME}"
        self._state: StateType = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION.format(provider="sepush.co.za")}
        self._attr_name = f"{NAME} {area.name}"
        self._attr_unique_id = f"{area.id}"

    @property
    def native_value(self) -> StateType:
        """Return the schedule state."""
        if not self.coordinator.data:
            return self._state

        area = self.coordinator.data.get(ATTR_AREAS, {}).get(self.area.id)

        forecast = area.get(ATTR_FORECAST)
        self._state = cast(StateType, STATE_OFF)

        if not forecast:
            return self._state

        next = forecast[0]
        if next.get(ATTR_STAGE) == Stage.NO_LOAD_SHEDDING:
            return self._state

        now = datetime.now(timezone.utc)
        if next.get(ATTR_START_TIME) <= now <= next.get(ATTR_END_TIME):
            self._state = cast(StateType, STATE_ON)

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return self._attrs

        data = self._attrs
        stage_schedule = (
            self.coordinator.data.get(ATTR_AREAS, {})
            .get(self.area.id, [])
            .get(ATTR_SCHEDULE)
        )

        data = []
        now = datetime.now(timezone.utc)
        for stage in stage_schedule:
            for s in stage_schedule[stage]:
                start_time = s[0]
                end_time = s[1]

                if start_time > now + timedelta(days=MAX_FORECAST_DAYS):
                    continue

                if end_time < now:
                    continue

                data.append(
                    {
                        ATTR_STAGE: Stage(stage),
                        ATTR_START_TIME: start_time,
                        ATTR_END_TIME: end_time,
                    }
                )

        area_schedule = data

        if area_schedule:
            data = get_sensor_attrs(area_schedule)
            for s in area_schedule:
                data[ATTR_SCHEDULE].append(
                    {
                        ATTR_STAGE: s.get(ATTR_STAGE).value,
                        ATTR_START_TIME: s.get(ATTR_START_TIME).isoformat(),
                        ATTR_END_TIME: s.get(ATTR_END_TIME).isoformat(),
                    }
                )

        area_forecast = (
            self.coordinator.data.get(ATTR_AREAS, {})
            .get(self.area.id, [])
            .get(ATTR_FORECAST)
        )
        if area_forecast:
            data = get_sensor_attrs(area_forecast)
            for f in area_forecast:
                data[ATTR_FORECAST].append(
                    {
                        ATTR_STAGE: f.get(ATTR_STAGE).value,
                        ATTR_START_TIME: f.get(ATTR_START_TIME).isoformat(),
                        ATTR_END_TIME: f.get(ATTR_END_TIME).isoformat(),
                    }
                )

        # data = area_schedule
        self._attrs.update(data)
        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self.async_write_ha_state()


def stage_forecast_to_data(stage_forecast: list) -> list:
    """Convert stage forecast to serializable data"""
    data = []
    for forecast in stage_forecast:
        for schedule in forecast.get(ATTR_SCHEDULE, []):
            data.append(
                {
                    ATTR_STAGE: forecast.get(ATTR_STAGE).value,
                    ATTR_START_TIME: schedule[0].isoformat(),
                    ATTR_END_TIME: schedule[1].isoformat(),
                }
            )
    return data


def get_sensor_attrs(forecast: list, stage: Stage = Stage.NO_LOAD_SHEDDING) -> dict:
    """Get sensor attributes for the given forecast and stage"""
    if not forecast:
        return {
            ATTR_STAGE: stage.value,
        }

    now = datetime.now(timezone.utc)
    data = {
        ATTR_STAGE: stage.value,
        ATTR_START_TIME: 0,
        ATTR_END_TIME: 0,
        ATTR_END_IN: 0,
        ATTR_START_IN: 0,
        ATTR_NEXT_STAGE: Stage.NO_LOAD_SHEDDING.value,
        ATTR_NEXT_START_TIME: 0,
        ATTR_NEXT_END_TIME: 0,
        ATTR_FORECAST: [],
        ATTR_SCHEDULE: [],
    }

    current, next = {}, {}
    if now < forecast[0].get(ATTR_START_TIME):
        # before
        next = forecast[0]
    elif forecast[0].get(ATTR_START_TIME) <= now <= forecast[0].get(ATTR_END_TIME, now):
        # during
        current = forecast[0]
        if len(forecast) > 1:
            next = forecast[1]
    elif forecast[0].get(ATTR_END_TIME) < now:
        # after
        if len(forecast) > 1:
            next = forecast[1]

    if current:
        data[ATTR_STAGE] = current.get(ATTR_STAGE).value
        data[ATTR_START_TIME] = current.get(ATTR_START_TIME).isoformat()
        data[ATTR_END_TIME] = current.get(ATTR_END_TIME).isoformat()

        end_time = current.get(ATTR_END_TIME)
        ends_in = end_time - now
        ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)
        ends_in = int(ends_in.total_seconds() / 60)  # minutes
        data[ATTR_END_IN] = ends_in

    if next:
        data[ATTR_NEXT_STAGE] = next.get(ATTR_STAGE).value
        data[ATTR_NEXT_START_TIME] = next.get(ATTR_START_TIME).isoformat()
        if ATTR_END_IN in next:
            data[ATTR_NEXT_END_TIME] = next.get(ATTR_END_TIME).isoformat()

        start_time = next.get(ATTR_START_TIME)
        starts_in = start_time - now
        starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)
        starts_in = int(starts_in.total_seconds() / 60)  # minutes
        data[ATTR_START_IN] = starts_in

    return data
