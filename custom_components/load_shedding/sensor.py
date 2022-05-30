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
    STATE_ON,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingDataUpdateCoordinator
from .const import (
    ATTR_START_TIME,
    ATTR_END_TIME,
    ATTR_START_IN,
    ATTR_END_IN,
    ATTR_SCHEDULE,
    ATTR_SCHEDULES,
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

    coordinator: LoadSheddingDataUpdateCoordinator = hass.data[DOMAIN]

    entities: list[Entity] = []
    suburb = Suburb(
        id=entry.data.get("suburb_id"),
        name=entry.data.get("suburb"),
        municipality=entry.data.get("municipality"),
        province=entry.data.get("province"),
    )
    entities.append(LoadSheddingStageSensorEntity(coordinator))
    entities.append(LoadSheddingScheduleSensorEntity(coordinator, suburb))

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""
    pass


class LoadSheddingStageSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Stage entity."""

    coordinator: LoadSheddingDataUpdateCoordinator

    def __init__(self, coordinator: LoadSheddingDataUpdateCoordinator) -> None:
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
            "via_device": (DOMAIN, self._device_id),
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

    coordinator: LoadSheddingDataUpdateCoordinator

    def __init__(self, coordinator: LoadSheddingDataUpdateCoordinator, suburb: Suburb) -> None:
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

        # stage = self.coordinator.data.get(ATTR_STAGE)

        schedules = self.coordinator.data.get(ATTR_SCHEDULES, {})
        # stages = schedules.get(self.suburb.id, {})

        schedule = schedules.get(self.suburb.id, {})

        if not schedule:
            return self._attrs

        tz = timezone.utc
        now = datetime.now(tz)
        days = MAX_FORECAST_DAYS
        starts_in = None
        for s in schedule:
            starts_at = datetime.fromisoformat(s[0])
            ends_at = datetime.fromisoformat(s[1])

            # if starts_in is None or starts_in.total_seconds() > 0:
            #     starts_in = starts_at - now
            #     starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)
            #     ends_in = ends_at - now
            #     ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)

            if starts_at.date() > now.date() + timedelta(days=days):
                continue
            if ends_at < now:
                continue
            self.schedule.append({
                ATTR_START_TIME: str(starts_at.isoformat()),
                ATTR_END_TIME: str(ends_at.isoformat()),
                # "start_in": str(starts_in),
                # "end_in": str(ends_in),
            })

        # next_start = self.schedule[0].get("start")
        # next_end = self.schedule[0].get("end")

        # tNow = now().strftime("%Y-%m-%d %H:%M:%S%z") | as_datetime
        # starts_at = strptime(next_start, "%Y-%m-%dT%H:%M:%S%z") | as_local
        # ends_at = strptime(next_end, "%Y-%m-%dT%H:%M:%S%z") | as_local
        # starts_in = starts_at - tNow
        # ends_in = ends_at - tNow

        # time_until = datetime.fromisoformat(self.schedule[0].get("start")) - now

    @property
    def native_value(self) -> StateType:
        """Return the schedule state."""

        # State: {{states('sensor.load_shedding_milnerton')}}
        #
        # {% set next_start = state_attr("sensor.load_shedding_milnerton", "next_start") -%}
        # {% set next_end = state_attr("sensor.load_shedding_milnerton", "next_end") -%}
        # StartsAt: {{ next_start }} (String UTC)
        # EndsAt  : {{ next_end }} (String UTC)
        #
        # {% set tNow = now().strftime("%Y-%m-%d %H:%M:%S%z") | as_datetime -%}
        #
        # {% if next_start == None or next_end == None %}
        #   Schedule is unavailable
        # {% else %}
        #   {% set starts_at = strptime(next_start, "%Y-%m-%dT%H:%M:%S%z") | as_local -%}
        #   {% set ends_at = strptime(next_end, "%Y-%m-%dT%H:%M:%S%z") | as_local -%}
        #   StartsAt: {{ starts_at }} (DateTime Local)
        #   EndsAt  : {{ ends_at }} (DateTime Local)
        #
        #   {% set starts_in = starts_at - tNow -%}
        #   {% set ends_in = ends_at - tNow -%}
        #
        #   StartsIn: {{ starts_in }} (TimeDelta)
        #   EndsIn  : {{ ends_in }} (TimeDelta)
        #
        #   ---
        #   Schedule:
        #   {{ starts_at.strftime("%H:%M") }} - {{ ends_at.strftime("%H:%M") }}
        #   Time Until:
        #   {%- if next_start != None -%}
        #     {% if starts_in.total_seconds() > 0 -%}
        #     Starts in {{ starts_in.seconds | timestamp_custom("%-Hh%M", False) }}
        #     {% else %}
        #     Ends in {{ ends_in.seconds | timestamp_custom("%-Hh%M", False) }}
        #     {% endif -%}
        #   {% endif -%}
        # {% endif %}
        tz = timezone.utc
        now = datetime.now(tz)
        if self.coordinator.data:
            stage = self.coordinator.data.get(ATTR_STAGE)
            if stage in [Stage.UNKNOWN, Stage.NO_LOAD_SHEDDING]:
                self._state = cast(StateType, STATE_OFF)
                return self._state

        if self.schedule:
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
            "via_device": (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return self._attrs

        tz = timezone.utc
        now = datetime.now(tz)
        starts_in = ends_in = None
        for s in self.schedule:
            starts_at = datetime.fromisoformat(s.get(ATTR_START_TIME))
            ends_at = datetime.fromisoformat(s.get(ATTR_END_TIME))
            starts_in = starts_at - now
            starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)
            ends_in = ends_at - now
            ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)
            if starts_in.total_seconds() > 0:
                break

        self._attrs.update(
            {
                ATTR_START_TIME: self.schedule[0].get(ATTR_START_TIME),
                ATTR_END_TIME: self.schedule[0].get(ATTR_END_TIME),
                ATTR_START_IN: str(starts_in),
                ATTR_END_IN: str(ends_in),
                ATTR_SCHEDULE: self.schedule,
            }
        )

        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""

        self.async_write_ha_state()
