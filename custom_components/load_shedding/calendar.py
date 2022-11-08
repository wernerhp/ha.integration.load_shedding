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
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_STAGE,
    ATTR_START_TIME,
    DOMAIN,
    NAME,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinators = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    area_coordinator = coordinators.get(ATTR_AREA)

    entities: list[Entity] = [LoadSheddingForecastCalendar(area_coordinator)]
    async_add_entities(entities)


class LoadSheddingForecastCalendar(
    LoadSheddingDevice, CoordinatorEntity, CalendarEntity
):
    """Define a LoadShedding Calendar entity."""

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        super().__init__(coordinator)
        self.data = self.coordinator.data

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
                for forecast in area_forecast:
                    forecast_stage = str(forecast.get(ATTR_STAGE))
                    forecast_start_time = forecast.get(ATTR_START_TIME)
                    forecast_end_time = forecast.get(ATTR_END_TIME)

                    if forecast_start_time <= start_date >= forecast_end_time:
                        continue
                    if forecast_start_time >= end_date <= forecast_end_time:
                        continue

                    event: CalendarEvent = CalendarEvent(
                        start=forecast_start_time,
                        end=forecast_end_time,
                        summary=forecast_stage,
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
        if data := self.coordinator.data:
            self.data = data
            self.async_write_ha_state()
