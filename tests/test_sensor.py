"""Tests for the Load Shedding sensor platform."""

from datetime import UTC, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from load_shedding.providers import Stage

from homeassistant.const import ATTR_NAME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.load_shedding.const import (
    ATTR_AREA,
    ATTR_END_TIME,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_PLANNED,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_TIME,
    DOMAIN,
)
from custom_components.load_shedding.sensor import (
    clean,
    get_sensor_attrs,
    stage_forecast_to_data,
)

from .conftest import AREA_ID, FROZEN_TIME

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_stage_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The stage sensors report the current stage per provider."""
    eskom = hass.states.get("sensor.load_shedding_stage_eskom")
    assert eskom is not None
    assert eskom.state == str(Stage.STAGE_2)

    capetown = hass.states.get("sensor.load_shedding_stage_capetown")
    assert capetown is not None
    assert capetown.state == str(Stage.STAGE_1)


async def test_area_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The area sensor is off when load shedding is not currently active."""
    state = hass.states.get(
        "sensor.load_shedding_area_za_gt_tsh_garsfontein_gaev"
    )
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["area_id"] == "za_gt_tsh_garsfontein_gaev"


async def test_quota_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The quota sensor reports the SePush request count."""
    state = hass.states.get("sensor.load_shedding_sepush_api_quota")
    assert state is not None
    assert state.state == "5"
    assert state.attributes["limit"] == 50


async def test_stage_sensor_updates_on_coordinator_push(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Pushing new stage data updates the stage sensor state."""
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_STAGE]
    new_data = dict(coordinator.data)
    new_data["eskom"] = {ATTR_NAME: "National", ATTR_PLANNED: []}
    coordinator.async_set_updated_data(new_data)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.load_shedding_stage_eskom")
    assert state.state == str(Stage.NO_LOAD_SHEDDING)


async def test_area_sensor_updates_active(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """An active forecast event turns the area sensor on."""
    freezer.move_to(FROZEN_TIME)
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_AREA]
    now = datetime(2026, 6, 18, 8, 0, tzinfo=UTC)
    new_data = dict(coordinator.data)
    new_data[AREA_ID] = {
        ATTR_FORECAST: [
            {
                ATTR_STAGE: Stage.STAGE_2,
                ATTR_START_TIME: now - timedelta(hours=1),
                ATTR_END_TIME: now + timedelta(hours=1),
            }
        ],
        ATTR_SCHEDULE: {},
        ATTR_EVENTS: [],
    }
    coordinator.async_set_updated_data(new_data)
    await hass.async_block_till_done()

    state = hass.states.get(
        "sensor.load_shedding_area_za_gt_tsh_garsfontein_gaev"
    )
    assert state.state == STATE_ON


async def test_quota_sensor_updates_on_coordinator_push(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Pushing new quota data updates the quota sensor state."""
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_QUOTA]
    coordinator.async_set_updated_data({"count": 12, "limit": 50, "type": "daily"})
    await hass.async_block_till_done()

    state = hass.states.get("sensor.load_shedding_sepush_api_quota")
    assert state.state == "12"


def test_get_sensor_attrs_no_forecast() -> None:
    """With no forecast only the stage attribute is returned."""
    attrs = get_sensor_attrs([], Stage.STAGE_3)
    assert attrs == {ATTR_STAGE: Stage.STAGE_3.value}


def test_get_sensor_attrs_upcoming_event(freezer: FrozenDateTimeFactory) -> None:
    """An upcoming event is surfaced as the next event with a countdown."""
    freezer.move_to("2026-06-18T08:00:00+00:00")
    now = datetime.now(UTC)
    forecast = [
        {
            ATTR_STAGE: Stage.STAGE_2,
            ATTR_START_TIME: now + timedelta(hours=1),
            ATTR_END_TIME: now + timedelta(hours=3),
        }
    ]
    attrs = get_sensor_attrs(forecast, Stage.STAGE_2)
    assert attrs[ATTR_STAGE] == Stage.STAGE_2.value
    assert attrs["starts_in"] == 60


def test_get_sensor_attrs_active_event(freezer: FrozenDateTimeFactory) -> None:
    """An active event reports an ``ends_in`` countdown."""
    freezer.move_to("2026-06-18T08:00:00+00:00")
    now = datetime.now(UTC)
    forecast = [
        {
            ATTR_STAGE: Stage.STAGE_4,
            ATTR_START_TIME: now - timedelta(hours=1),
            ATTR_END_TIME: now + timedelta(hours=2),
        }
    ]
    attrs = get_sensor_attrs(forecast, Stage.STAGE_4)
    assert attrs["ends_in"] == 120


def test_clean_removes_empty_defaults() -> None:
    """clean strips keys whose value equals the documented empty default."""
    data = {ATTR_SCHEDULE: [], ATTR_STAGE: Stage.STAGE_1.value}
    assert clean(data) == {ATTR_STAGE: Stage.STAGE_1.value}


def test_stage_forecast_to_data() -> None:
    """stage_forecast_to_data flattens schedules into serializable dicts."""
    start = datetime(2026, 6, 18, 18, 0, tzinfo=UTC)
    end = datetime(2026, 6, 18, 20, 30, tzinfo=UTC)
    forecast = [
        {
            ATTR_STAGE: Stage.STAGE_2,
            ATTR_SCHEDULE: [(start, end)],
        }
    ]
    data = stage_forecast_to_data(forecast)
    assert data == [
        {
            ATTR_STAGE: Stage.STAGE_2.value,
            ATTR_START_TIME: start.isoformat(),
            ATTR_END_TIME: end.isoformat(),
        }
    ]


async def test_area_sensor_attributes_clear_when_forecast_empties(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Forecast-derived attributes clear when the forecast empties (C2)."""
    freezer.move_to(FROZEN_TIME)
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_AREA]
    entity_id = "sensor.load_shedding_area_za_gt_tsh_garsfontein_gaev"
    now = datetime(2026, 6, 18, 8, 0, tzinfo=UTC)

    new_data = dict(coordinator.data)
    new_data[AREA_ID] = {
        ATTR_FORECAST: [
            {
                ATTR_STAGE: Stage.STAGE_2,
                ATTR_START_TIME: now + timedelta(hours=1),
                ATTR_END_TIME: now + timedelta(hours=3),
            }
        ],
        ATTR_SCHEDULE: {},
        ATTR_EVENTS: [],
    }
    coordinator.async_set_updated_data(new_data)
    await hass.async_block_till_done()

    attrs = hass.states.get(entity_id).attributes
    assert attrs[ATTR_FORECAST]
    assert "starts_in" in attrs

    empty_data = dict(coordinator.data)
    empty_data[AREA_ID] = {ATTR_FORECAST: [], ATTR_SCHEDULE: {}, ATTR_EVENTS: []}
    coordinator.async_set_updated_data(empty_data)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == STATE_OFF
    assert not state.attributes.get(ATTR_FORECAST)
    assert "starts_in" not in state.attributes
    assert "start_time" not in state.attributes


async def test_stage_sensor_attributes_clear_when_planned_empties(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stage planned-derived attributes clear when the planned list empties (C2)."""
    freezer.move_to(FROZEN_TIME)
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_STAGE]
    entity_id = "sensor.load_shedding_stage_eskom"

    attrs = hass.states.get(entity_id).attributes
    assert attrs[ATTR_PLANNED]
    assert "next_stage" in attrs

    new_data = dict(coordinator.data)
    new_data["eskom"] = {ATTR_NAME: "National", ATTR_PLANNED: []}
    coordinator.async_set_updated_data(new_data)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == str(Stage.NO_LOAD_SHEDDING)
    assert not state.attributes.get(ATTR_PLANNED)
    assert "next_stage" not in state.attributes
    assert "ends_in" not in state.attributes


async def test_area_sensor_merges_contiguous_end_time(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Area sensor extends end_time across a contiguous stage change (#54 wiring)."""
    freezer.move_to(FROZEN_TIME)
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_AREA]
    entity_id = "sensor.load_shedding_area_za_gt_tsh_garsfontein_gaev"
    now = datetime(2026, 6, 18, 8, 0, tzinfo=UTC)

    new_data = dict(coordinator.data)
    new_data[AREA_ID] = {
        ATTR_FORECAST: [
            {
                ATTR_STAGE: Stage.STAGE_2,
                ATTR_START_TIME: now - timedelta(hours=1),
                ATTR_END_TIME: now + timedelta(hours=1),
            },
            {
                ATTR_STAGE: Stage.STAGE_4,
                ATTR_START_TIME: now + timedelta(hours=1),
                ATTR_END_TIME: now + timedelta(hours=3),
            },
        ],
        ATTR_SCHEDULE: {},
        ATTR_EVENTS: [],
    }
    coordinator.async_set_updated_data(new_data)
    await hass.async_block_till_done()

    attrs = hass.states.get(entity_id).attributes
    assert attrs[ATTR_END_TIME] == (now + timedelta(hours=3)).isoformat()


async def test_stage_sensor_preserves_next_fields(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Stage sensor keeps per-stage next_* fields (planned is not merged, #54 wiring)."""
    freezer.move_to(FROZEN_TIME)
    attrs = hass.states.get("sensor.load_shedding_stage_eskom").attributes
    assert attrs["next_stage"] == Stage.STAGE_4.value
    assert "next_start_time" in attrs
