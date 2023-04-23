"""Support for the LoadShedding service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from homeassistant.components.sensor import RestoreSensor
from homeassistant.components.binary_sensor import (
    BinarySensorEntityDescription,
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    STATE_ON,
    STATE_OFF,
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
    area_coordinator = coordinators.get(ATTR_AREA)

    entities: list[Entity] = []
    for area in area_coordinator.areas:
        area_entity = LoadSheddingAreaBinarySensorEntity(area_coordinator, area)
        entities.append(area_entity)

    async_add_entities(entities)


@dataclass
class LoadSheddingBinarySensorDescription(BinarySensorEntityDescription):
    """Class describing LoadShedding sensor entities."""


class LoadSheddingAreaBinarySensorEntity(
    LoadSheddingDevice,
    CoordinatorEntity,
    # RestoreSensor,
    BinarySensorEntity,
):
    """Define a LoadShedding Area sensor entity."""

    coordinator: CoordinatorEntity

    def __init__(self, coordinator: CoordinatorEntity, area: Area) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.area = area
        self.data = self.coordinator.data.get(self.area.id)
        self._sensor_type = BinarySensorDeviceClass.POWER

        self.entity_description = LoadSheddingBinarySensorDescription(
            # key=f"{DOMAIN} schedule {area.id}",
            # icon="mdi:calendar",
            # name=f"{DOMAIN} schedule {area.name}",
            # entity_registry_enabled_default=True,
            key=f"{DOMAIN} schedule {area.id}",
            name=f"{DOMAIN} schedule {area.name}",
            device_class=BinarySensorDeviceClass.POWER,
            # entity_category=EntityCategory.DIAGNOSTIC,
            # on_state=0,
        )
        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}_Binarysensor_{area.id}"
        )
        self.entity_id = f"{DOMAIN}.{DOMAIN}_area_{area.id}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        # if restored_data := await self.async_get_last_sensor_data():
        #     self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        return self.area.name

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return True

    @property
    def native_value(self) -> StateType:
        """Return the area state."""
        if not self.data:
            return self._attr_is_on
            return self._attr_native_value

        events = self.data.get(ATTR_FORECAST, [])

        if not events:
            return STATE_OFF

        now = datetime.now(timezone.utc)

        for event in events:
            if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                continue

            if event.get(ATTR_START_TIME) <= now <= event.get(ATTR_END_TIME):
                self._attr_native_value = cast(StateType, STATE_ON)
                self._attr_is_on = cast(StateType, STATE_ON)
                break

            if event.get(ATTR_START_TIME) > now:
                self._attr_native_value = cast(StateType, STATE_OFF)
                self._attr_is_on = cast(StateType, STATE_OFF)
                break

            if event.get(ATTR_STAGE) == Stage.NO_LOAD_SHEDDING:
                self._attr_native_value = cast(StateType, STATE_OFF)
                self._attr_is_on = cast(StateType, STATE_OFF)
                break

        return self._attr_is_on
        return self._attr_native_value

    # @property
    # def is_on(self) -> bool | None:
    #     return self.native_value == STATE_OFF

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(timezone.utc)
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
    """Get Binarysensor attributes for the given forecast and stage"""
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
