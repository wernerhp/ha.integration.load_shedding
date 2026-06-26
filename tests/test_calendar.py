"""Tests for the Load Shedding calendar platform."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    SERVICE_GET_EVENTS,
)
from homeassistant.core import HomeAssistant

from custom_components.load_shedding.const import (
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_STAGE,
    ATTR_START_TIME,
    DOMAIN,
)

from .conftest import AREA_ID

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_calendar_entity_created(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The forecast calendar entity is created."""
    state = hass.states.get("calendar.load_shedding_forecast")
    assert state is not None


async def test_calendar_get_events(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The calendar returns forecast events within the requested range."""
    response = await hass.services.async_call(
        CALENDAR_DOMAIN,
        SERVICE_GET_EVENTS,
        {
            "entity_id": "calendar.load_shedding_forecast",
            "start_date_time": "2026-06-18T00:00:00+00:00",
            "end_date_time": "2026-06-25T00:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response["calendar.load_shedding_forecast"]["events"]
    assert events
    assert events[0]["location"] == "Garsfontein"


async def test_calendar_multi_stage_events(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Consecutive forecast slots merge into a single multi-stage event."""
    entry = init_integration
    area_coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_AREA]

    start = datetime(2026, 6, 18, 18, 0, tzinfo=UTC)
    mid = start + timedelta(hours=2)
    end = mid + timedelta(hours=2)
    area_coordinator.data[AREA_ID][ATTR_FORECAST] = [
        {ATTR_STAGE: 2, ATTR_START_TIME: start, ATTR_END_TIME: mid},
        {ATTR_STAGE: 4, ATTR_START_TIME: mid, ATTR_END_TIME: end},
    ]

    entity = hass.data["calendar"].get_entity("calendar.load_shedding_forecast")
    entity.multi_stage_events = True
    # The event list is cached and only rebuilt on a coordinator update.
    area_coordinator.async_set_updated_data(area_coordinator.data)
    await hass.async_block_till_done()
    events = await entity.async_get_events(
        hass,
        datetime(2026, 6, 18, 0, 0, tzinfo=UTC),
        datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
    )
    assert len(events) == 1
    assert events[0].summary == "2/4"
    assert events[0].end == end


async def test_calendar_updates_on_coordinator_push(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A coordinator push refreshes the calendar without error."""
    entry = init_integration
    area_coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_AREA]
    area_coordinator.async_set_updated_data(dict(area_coordinator.data))
    await hass.async_block_till_done()

    state = hass.states.get("calendar.load_shedding_forecast")
    assert state is not None
