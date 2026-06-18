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
from .helpers import build_calendar_events, current_event, events_in_range
from .const import (
    ATTR_AREA,
    ATTR_FORECAST,
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
        event = current_event(self._build_event_dicts(), now)
        return self._to_calendar_event(event) if event else None

    def _build_event_dicts(self) -> list[dict]:
        """Build the ordered list of forecast events as plain dicts."""
        area_forecasts = [
            {
                "id": area.id,
                "name": area.name,
                ATTR_FORECAST: self.data.get(area.id, {}).get(ATTR_FORECAST),
            }
            for area in self.coordinator.areas
        ]
        return build_calendar_events(area_forecasts, self.multi_stage_events)

    @staticmethod
    def _to_calendar_event(event: dict) -> CalendarEvent:
        """Wrap a plain event dict into a HA CalendarEvent."""
        return CalendarEvent(
            start=event["start"],
            end=event["end"],
            summary=event["summary"],
            location=event["location"],
            description=f"{NAME}",
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events = events_in_range(self._build_event_dicts(), start_date, end_date)
        return [self._to_calendar_event(event) for event in events]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data
        # Writing state re-reads the live ``event`` property so the calendar
        # reflects (or clears) the current event whenever the coordinator
        # refreshes.
        self.async_write_ha_state()
