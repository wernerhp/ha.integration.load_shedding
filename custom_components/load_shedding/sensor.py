"""Support for the LoadShedding service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from load_shedding.providers import Area, Stage

from homeassistant.components.sensor import RestoreSensor, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingDevice
from .const import (
    ATTR_AREA,
    ATTR_AREA_ID,
    ATTR_END_IN,
    ATTR_END_TIME,
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
    coordinators = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    stage_coordinator = coordinators.get(ATTR_STAGE)
    area_coordinator = coordinators.get(ATTR_AREA)
    quota_coordinator = coordinators.get(ATTR_QUOTA)

    entities: list[Entity] = []
    for idx in stage_coordinator.data:
        stage_entity = LoadSheddingStageSensorEntity(stage_coordinator, idx)
        entities.append(stage_entity)

    for area in area_coordinator.areas:
        area_entity = LoadSheddingAreaSensorEntity(area_coordinator, area)
        entities.append(area_entity)

    quota_entity = LoadSheddingQuotaSensorEntity(quota_coordinator)
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
        self.data = self.coordinator.data.get(self.idx)

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_{self.idx}"
        self.entity_id = f"{DOMAIN}.{DOMAIN}_stage_{idx}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        """Return the stage sensor name."""
        name = self.data.get("name", "Unknown")
        return f"{name} Stage"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if not self.data:
            return self._attr_native_value

        planned = self.data.get(ATTR_PLANNED, [])
        if not planned:
            return Stage.NO_LOAD_SHEDDING

        stage = planned[0].get(ATTR_STAGE, Stage.NO_LOAD_SHEDDING)

        self._attr_native_value = cast(StateType, stage)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        self.data = self.coordinator.data.get(self.idx)
        if not self.data:
            return self._attr_extra_state_attributes

        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(UTC)
        data = dict(self._attr_extra_state_attributes)
        if events := self.data.get(ATTR_PLANNED, []):
            data[ATTR_PLANNED] = []
            for event in events:
                if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                    continue

                planned = {
                    ATTR_STAGE: event.get(ATTR_STAGE),
                    ATTR_START_TIME: event.get(ATTR_START_TIME),
                }
                if ATTR_END_TIME in event:
                    planned[ATTR_END_TIME] = event.get(ATTR_END_TIME)

                data[ATTR_PLANNED].append(planned)

        cur_stage = Stage.NO_LOAD_SHEDDING

        planned = []
        if ATTR_PLANNED in data:
            planned = data[ATTR_PLANNED]
            cur_stage = planned[0].get(ATTR_STAGE, Stage.NO_LOAD_SHEDDING)

        attrs = get_sensor_attrs(planned, cur_stage)
        attrs[ATTR_PLANNED] = planned
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes.update(attrs)
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data.get(self.idx)
            # Explicitly get the native value to force state update
            self._attr_native_value = self.native_value
            self.async_write_ha_state()


class LoadSheddingAreaSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Area sensor entity."""

    def __init__(self, coordinator: CoordinatorEntity, area: Area) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.area = area
        self.data = self.coordinator.data.get(self.area.id)

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
        """Return the area sensor name."""
        return self.area.name

    @property
    def native_value(self) -> StateType:
        """Return the area state."""
        if not self.data:
            return self._attr_native_value

        events = self.data.get(ATTR_FORECAST, [])

        if not events:
            return STATE_OFF

        now = datetime.now(UTC)

        for event in events:
            if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                continue

            if event.get(ATTR_START_TIME) <= now <= event.get(ATTR_END_TIME):
                self._attr_native_value = cast(StateType, STATE_ON)
                break

            if event.get(ATTR_START_TIME) > now:
                self._attr_native_value = cast(StateType, STATE_OFF)
                break

            if event.get(ATTR_STAGE) == Stage.NO_LOAD_SHEDDING:
                self._attr_native_value = cast(StateType, STATE_OFF)
                break

        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(UTC)
        data = dict(self._attr_extra_state_attributes)
        if events := self.data.get(ATTR_FORECAST, []):
            data[ATTR_FORECAST] = []
            for event in events:
                if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                    continue

                forecast = {
                    ATTR_STAGE: event.get(ATTR_STAGE),
                    ATTR_START_TIME: event.get(ATTR_START_TIME),
                    ATTR_END_TIME: event.get(ATTR_END_TIME),
                }

                data[ATTR_FORECAST].append(forecast)

        forecast = []
        if ATTR_FORECAST in data:
            forecast = data[ATTR_FORECAST]

        attrs = get_sensor_attrs(forecast)
        attrs[ATTR_AREA_ID] = self.area.id
        attrs[ATTR_FORECAST] = forecast
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes.update(attrs)
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data.get(self.area.id)
            # Explicitly get the native value to force state update
            self._attr_native_value = self.native_value
            self.async_write_ha_state()


class LoadSheddingQuotaSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Quota entity."""

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        """Initialize the quota sensor."""
        super().__init__(coordinator)
        self.data = self.coordinator.data

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
        """Return the quota sensor name."""
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

        attrs = self.data
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes.update(attrs)
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data
            # Explicitly get the native value to force state update
            self._attr_native_value = self.native_value
            self.async_write_ha_state()


def stage_forecast_to_data(stage_forecast: list) -> list:
    """Convert stage forecast to serializable data."""
    data = []
    for forecast in stage_forecast:
        transformed_list = [
            {
                ATTR_STAGE: forecast.get(ATTR_STAGE).value,
                ATTR_START_TIME: schedule[0].isoformat(),
                ATTR_END_TIME: schedule[1].isoformat(),
            }
            for schedule in forecast.get(ATTR_SCHEDULE, [])
        ]
        data.extend(transformed_list)
    return data


def get_sensor_attrs(forecast: list, stage: Stage = Stage.NO_LOAD_SHEDDING) -> dict:
    """Get sensor attributes for the given forecast and stage."""
    if not forecast:
        return {
            ATTR_STAGE: stage.value,
        }

    now = datetime.now(UTC)
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
        try:
            data[ATTR_STAGE] = cur.get(ATTR_STAGE).value
        except AttributeError:
            data[ATTR_STAGE] = Stage.NO_LOAD_SHEDDING.value
        data[ATTR_START_TIME] = cur.get(ATTR_START_TIME).isoformat()
        if ATTR_END_TIME in cur:
            data[ATTR_END_TIME] = cur.get(ATTR_END_TIME).isoformat()

            end_time = cur.get(ATTR_END_TIME)
            ends_in = end_time - now
            ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)
            ends_in = int(ends_in.total_seconds() / 60)  # minutes
            data[ATTR_END_IN] = ends_in

    if nxt:
        try:
            data[ATTR_NEXT_STAGE] = nxt.get(ATTR_STAGE).values
        except AttributeError:
            data[ATTR_NEXT_STAGE] = Stage.NO_LOAD_SHEDDING.value

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
    """Remove default values from dict."""
    for key, value in CLEAN_DATA.items():
        if key not in data:
            continue
        if data[key] == value:
            del data[key]

    return data
