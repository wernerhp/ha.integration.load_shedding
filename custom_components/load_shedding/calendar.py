"""Support for the LoadShedding service."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from . import LoadSheddingDevice
from .const import (
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_TIME,
    DOMAIN,
    NAME,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    entities: list[Entity] = [LoadSheddingForecastCalendar(coordinator)]
    async_add_entities(entities)


class LoadSheddingForecastCalendar(
    LoadSheddingDevice, CoordinatorEntity, CalendarEntity
):
    """Define a LoadShedding Calendar entity."""

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        super().__init__(coordinator)
        self.data = self.coordinator.data.get(ATTR_SCHEDULE, {})

        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}_calendar_forecast"
        )
        self._event: CalendarEvent | None = None
        self.entity_id = f"{DOMAIN}.{DOMAIN}_forecast"

    @property
    def name(self) -> str | None:
        return f"{NAME} Forecast"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        return self._event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events = []

        for area in self.coordinator.areas:
            area_forecast = self.data.get(area.id, {}).get(ATTR_FORECAST)
            if area_forecast:
                for f in area_forecast:
                    event: CalendarEvent = CalendarEvent(
                        start=f.get(ATTR_START_TIME),
                        end=f.get(ATTR_END_TIME),
                        summary=str(f.get(ATTR_STAGE)),
                        location=area.name,
                        description=f"{NAME}",
                    )
                    events.append(event)

        if events:
            self._event = events[0]

        return events

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data.get(ATTR_STAGE):
            self.data = data
            self.async_write_ha_state()
