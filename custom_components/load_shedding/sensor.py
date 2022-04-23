"""Support for the LoadShedding service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, cast

from load_shedding.providers import Suburb

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingDataUpdateCoordinator
from .const import (
    ATTR_NEXT_END,
    ATTR_NEXT_START,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_SUBURBS,
    ATTR_TIME_UNTIL,
    ATTRIBUTION,
    DOMAIN,
    NAME,
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
    entities.append(LoadSheddingSensorEntity(coordinator, suburb))

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing Speedtest sensor entities."""

    pass


class LoadSheddingSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define an LoadShedding entity."""

    coordinator: LoadSheddingDataUpdateCoordinator

    def __init__(
        self,
        coordinator: LoadSheddingDataUpdateCoordinator,
        suburb: Suburb,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.suburb = suburb

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {suburb.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} {suburb.name}",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        self._device_id = "loadshedding.eskom.co.za"  # description.key
        self._state: StateType = None
        self._attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        self._attr_name = f"{NAME} {suburb.name}"
        self._attr_unique_id = description.key

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        if self.coordinator.data:
            # state = self.coordinator.data.get(self.suburb.id)
            state = self.coordinator.data.get(ATTR_STAGE)
            self._state = cast(StateType, state)
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
            # "entry_type": "service",
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return self._attrs

        suburbs = self.coordinator.data.get(ATTR_SUBURBS, {})
        schedule = suburbs.get(self.suburb.id, {})

        if not schedule:
            return self._attrs

        tz = timezone.utc
        now = datetime.now(tz)
        days = 7
        forecast = []
        for s in schedule:
            start = datetime.fromisoformat(s[0])
            end = datetime.fromisoformat(s[1])
            if start.date() > now.date() + timedelta(days=days):
                continue
            if end < now:
                continue
            forecast.append({"start": start.isoformat(), "end": end.isoformat()})

        # time_until = datetime.fromisoformat(forecast[0].get("start")) - now

        self._attrs.update(
            {
                ATTR_NEXT_START: forecast[0].get("start"),
                ATTR_NEXT_END: forecast[0].get("end"),
                # ATTR_TIME_UNTIL: time_until,
                ATTR_SCHEDULE: forecast,
            }
        )

        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""

        self.async_write_ha_state()
