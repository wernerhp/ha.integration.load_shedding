"""Support for the LoadShedding service."""
from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingDevice
from .const import (
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_STAGE,
    ATTR_START_TIME,
    CONF_MULTI_STAGE_EVENTS,
    DOMAIN,
    NAME,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinators = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    area_coordinator = coordinators.get(ATTR_AREA)

    multi_stage_events = False
    if entry.options.get(CONF_MULTI_STAGE_EVENTS):
        multi_stage_events = True

    entities: list[Entity] = [
        LoadSheddingForecastCalendar(area_coordinator, multi_stage_events)
    ]
    async_add_entities(entities)


class LoadSheddingForecastCalendar(
    LoadSheddingDevice, CoordinatorEntity, CalendarEntity
):
    """Define a LoadShedding Calendar entity."""

    def __init__(
        self, coordinator: CoordinatorEntity, multi_stage_events: bool
    ) -> None:
        """Initialize the forecast calendar."""
        super().__init__(coordinator)
        self.data = self.coordinator.data

        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}_calendar_forecast"
        )
        self._event: CalendarEvent | None = None
        self.entity_id = f"{CALENDAR_DOMAIN}.{DOMAIN}_forecast"
        self.multi_stage_events = multi_stage_events

    @property
    def name(self) -> str | None:
        """Return the forecast calendar name."""
        return f"{NAME} Forecast"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event, or None.

        Computed live from the coordinator data so that the calendar reliably
        clears when load shedding ends (the forecast becomes empty) instead of
        holding on to a stale event.
        """
        now = datetime.now(UTC)
        for event in self._build_events():
            if event.end > now:
                return event
        return None

    def _build_events(self) -> list[CalendarEvent]:
        """Build the full, ordered list of forecast calendar events."""
        events: list[CalendarEvent] = []

        for area in self.coordinator.areas:
            area_forecast = self.data.get(area.id, {}).get(ATTR_FORECAST)
            if not area_forecast:
                continue
            for forecast in area_forecast:
                events.append(
                    CalendarEvent(
                        start=forecast.get(ATTR_START_TIME),
                        end=forecast.get(ATTR_END_TIME),
                        summary=str(forecast.get(ATTR_STAGE)),
                        location=area.name,
                        description=f"{NAME}",
                    )
                )

        events.sort(key=lambda event: event.start)

        if self.multi_stage_events:
            merged: list[CalendarEvent] = []
            for event in events:
                if merged and merged[-1].end == event.start:
                    merged[-1].summary = f"{merged[-1].summary}/{event.summary}"
                    merged[-1].end = event.end
                else:
                    merged.append(event)
            events = merged

        return events

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events = []
        for event in self._build_events():
            # Exclude events fully outside the requested window.
            if event.end <= start_date:
                continue
            if event.start >= end_date:
                continue
            events.append(event)

        return events

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data
        # Recompute and write state so the calendar reflects (or clears) the
        # current event whenever the coordinator refreshes.
        self._event = self.event
        self.async_write_ha_state()
