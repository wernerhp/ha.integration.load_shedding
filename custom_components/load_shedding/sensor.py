"""Support for the LoadShedding service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from homeassistant.components.sensor import RestoreSensor, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from load_shedding.providers import Area, Stage
from . import LoadSheddingDevice
from .const import (
    ATTR_AREA,
    ATTR_END_IN,
    ATTR_END_TIME,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_LAST_UPDATE,
    ATTR_NEXT_END_TIME,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_PLANNED,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_IN,
    ATTR_START_TIME,
    ATTRIBUTION,
    DOMAIN,
    NAME,
)

DEFAULT_DATA = {
    ATTR_STAGE: Stage.NO_LOAD_SHEDDING.value,
    ATTR_START_TIME: 0,
    ATTR_END_TIME: 0,
    ATTR_END_IN: 0,
    ATTR_START_IN: 0,
    ATTR_NEXT_STAGE: Stage.NO_LOAD_SHEDDING.value,
    ATTR_NEXT_START_TIME: 0,
    ATTR_NEXT_END_TIME: 0,
    ATTR_PLANNED: [],
    ATTR_FORECAST: [],
    ATTR_SCHEDULE: [],
    ATTR_LAST_UPDATE: None,
    ATTR_ATTRIBUTION: ATTRIBUTION.format(provider="sepush.co.za"),
}

CLEAN_DATA = {
    ATTR_PLANNED: [],
    ATTR_FORECAST: [],
    ATTR_SCHEDULE: [],
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    entities: list[Entity] = []
    for idx in coordinator.data.get(ATTR_STAGE):
        stage_entity = LoadSheddingStageSensorEntity(coordinator, idx)
        entities.append(stage_entity)

    for area in coordinator.areas:
        area_entity = LoadSheddingScheduleSensorEntity(coordinator, area)
        entities.append(area_entity)

    quota_entity = LoadSheddingQuotaSensorEntity(coordinator)
    entities.append(quota_entity)

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""


class LoadSheddingStageSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Stage entity."""

    def __init__(self, coordinator: CoordinatorEntity, idx: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.idx = idx

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )
        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_{self.idx}"
        self.entity_id = f"{DOMAIN}.{DOMAIN}_stage_{idx}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        name = self.data.get("name", "Unknown")
        return f"{name} Stage"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if not self.data:
            return self._attr_native_value

        planned = self.data.get(ATTR_PLANNED, [])
        if not planned:
            return self._attr_native_value

        stage = planned[0].get(ATTR_STAGE, Stage.UNKNOWN)
        if stage in [Stage.UNKNOWN]:
            return self._attr_native_value

        self._attr_native_value = cast(StateType, stage)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        if not self.data:
            return self._attr_extra_state_attributes

        planned = self.data.get(ATTR_PLANNED, [])
        if not planned:
            return self._attr_extra_state_attributes

        now = datetime.now(timezone.utc)
        data = get_sensor_attrs(planned, planned[0].get(ATTR_STAGE, Stage.UNKNOWN))
        data[ATTR_PLANNED] = []
        for event in planned:
            if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                continue
            forecast = {
                ATTR_STAGE: event.get(ATTR_STAGE).value,
                ATTR_START_TIME: event.get(ATTR_START_TIME).isoformat(),
            }
            if ATTR_END_TIME in event:
                forecast[ATTR_END_TIME] = event.get(ATTR_END_TIME).isoformat()

            data[ATTR_PLANNED].append(forecast)

        self._attr_extra_state_attributes.update(clean(data))
        self._attr_extra_state_attributes[
            ATTR_LAST_UPDATE
        ] = self.coordinator.last_update
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data.get(ATTR_STAGE):
            self.data = data
            self.async_write_ha_state()


class LoadSheddingScheduleSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Schedule entity."""

    coordinator: CoordinatorEntity

    def __init__(self, coordinator: CoordinatorEntity, area: Area) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.data = self.coordinator.data.get(ATTR_AREA, [])
        self.area = area

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {area.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} schedule {area.name}",
            entity_registry_enabled_default=True,
        )
        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}_sensor_{area.id}"
        )
        self.entity_id = f"{DOMAIN}.{DOMAIN}_area_{area.id}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        return self.area.name

    @property
    def native_value(self) -> StateType:
        """Return the schedule state."""
        if not self.data:
            return self._attr_native_value

        area = self.data.get(self.area.id, {})
        events = area.get(ATTR_FORECAST, [])

        if not events:
            return self._attr_native_value

        nxt = events[0]
        if nxt.get(ATTR_STAGE) == Stage.NO_LOAD_SHEDDING:
            return self._attr_native_value

        now = datetime.now(timezone.utc)
        if nxt.get(ATTR_START_TIME) <= now <= nxt.get(ATTR_END_TIME):
            self._attr_native_value = cast(StateType, STATE_ON)

        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(timezone.utc)
        data = self._attr_extra_state_attributes
        area_events = self.data.get(self.area.id, {}).get(ATTR_FORECAST)
        if area_events:
            data = get_sensor_attrs(area_events)
            data[ATTR_FORECAST] = []
            for event in area_events:
                if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                    continue
                data[ATTR_FORECAST].append(
                    {
                        ATTR_STAGE: event.get(ATTR_STAGE).value,
                        ATTR_START_TIME: event.get(ATTR_START_TIME).isoformat(),
                        ATTR_END_TIME: event.get(ATTR_END_TIME).isoformat(),
                    }
                )

        self._attr_extra_state_attributes.update(clean(data))
        self._attr_extra_state_attributes[
            ATTR_LAST_UPDATE
        ] = self.coordinator.last_update
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data.get(ATTR_AREA):
            self.data = data
            self.async_write_ha_state()


class LoadSheddingQuotaSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Quota entity."""

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.data = self.coordinator.data.get(ATTR_QUOTA, {})

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} SePush Quota",
            icon="mdi:api",
            name=f"{DOMAIN} SePush Quota",
            entity_registry_enabled_default=True,
        )
        self._attr_name = f"{NAME} SePush Quota"
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_se_push_quota"
        self.entity_id = f"{DOMAIN}.{DOMAIN}_sepush_api_quota"

    @property
    def name(self) -> str | None:
        return "SePush API Quota"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if not self.data:
            return self._attr_native_value

        count = int(self.data.get("count", 0))
        self._attr_native_value = cast(StateType, count)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        if not self.data:
            return self._attr_extra_state_attributes

        self._attr_extra_state_attributes.update(self.data)
        self._attr_extra_state_attributes[
            ATTR_LAST_UPDATE
        ] = self.coordinator.last_update
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data.get(ATTR_QUOTA):
            self.data = data
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
    data = dict(DEFAULT_DATA)
    data[ATTR_STAGE] = stage.value

    cur, nxt = {}, {}
    if now < forecast[0].get(ATTR_START_TIME):
        # before
        nxt = forecast[0]
    elif forecast[0].get(ATTR_START_TIME) <= now <= forecast[0].get(ATTR_END_TIME, now):
        # during
        cur = forecast[0]
        if len(forecast) > 1:
            nxt = forecast[1]
    elif forecast[0].get(ATTR_END_TIME) < now:
        # after
        if len(forecast) > 1:
            nxt = forecast[1]

    if cur:
        data[ATTR_STAGE] = cur.get(ATTR_STAGE).value
        data[ATTR_START_TIME] = cur.get(ATTR_START_TIME).isoformat()
        if ATTR_END_TIME in cur:
            data[ATTR_END_TIME] = cur.get(ATTR_END_TIME).isoformat()

            end_time = cur.get(ATTR_END_TIME)
            ends_in = end_time - now
            ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)
            ends_in = int(ends_in.total_seconds() / 60)  # minutes
            data[ATTR_END_IN] = ends_in

    if nxt:
        data[ATTR_NEXT_STAGE] = nxt.get(ATTR_STAGE).value
        data[ATTR_NEXT_START_TIME] = nxt.get(ATTR_START_TIME).isoformat()
        if ATTR_END_TIME in nxt:
            data[ATTR_NEXT_END_TIME] = nxt.get(ATTR_END_TIME).isoformat()

        start_time = nxt.get(ATTR_START_TIME)
        starts_in = start_time - now
        starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)
        starts_in = int(starts_in.total_seconds() / 60)  # minutes
        data[ATTR_START_IN] = starts_in

    return data


def clean(data: dict) -> dict:
    """Remove default values from dict"""
    for (key, value) in CLEAN_DATA.items():
        if key not in data:
            continue
        if data[key] == value:
            del data[key]

    return data
