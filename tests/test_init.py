"""Tests for the Load Shedding integration setup, unload and coordinators."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from load_shedding.libs.sepush import SePushError
from load_shedding.providers import Stage
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_NAME, CONF_API_KEY, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.load_shedding import (
    LoadSheddingAreaCoordinator,
    LoadSheddingStageCoordinator,
    async_migrate_entry,
    utc_dt,
)
from custom_components.load_shedding.const import (
    ATTR_AREA,
    ATTR_EVENTS,
    ATTR_FORECAST,
    ATTR_PLANNED,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_TIME,
    ATTR_END_TIME,
    CONF_AREAS,
    DOMAIN,
    STAGE_UPDATE_INTERVAL,
)

from .conftest import (
    AREA_ID,
    FROZEN_TIME,
    LEGACY_AREA_ID,
    LEGACY_AREA_NAME,
    STATUS_DATA,
    build_config_entry,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The integration sets up, registers entities and unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.data
    coordinators = hass.data[DOMAIN][entry.entry_id]
    assert set(coordinators) == {ATTR_STAGE, ATTR_AREA}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_without_api_key_fails(
    hass: HomeAssistant, mock_sepush: MagicMock
) -> None:
    """Setup fails when no API key is configured."""
    entry = build_config_entry(api_key=None)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_without_areas_fails(
    hass: HomeAssistant, mock_sepush: MagicMock
) -> None:
    """Setup fails when no areas are configured."""
    entry = build_config_entry(areas=[])
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_legacy_area_id_creates_repair_issue(
    hass: HomeAssistant, mock_sepush: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """A legacy v2 area id raises a repair issue and is skipped."""
    freezer.move_to(FROZEN_TIME)
    mock_sepush.area.side_effect = SePushError("bad area", status_code=400)
    entry = build_config_entry(
        areas=[
            {
                CONF_ID: LEGACY_AREA_ID,
                CONF_NAME: LEGACY_AREA_NAME,
                "description": LEGACY_AREA_NAME,
            }
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(
        DOMAIN, f"invalid_area_ids_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {"areas": LEGACY_AREA_NAME}


async def test_valid_area_clears_stale_repair_issue(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A previously created invalid-area issue is removed when areas are valid."""
    entry = init_integration
    issue_registry = ir.async_get(hass)
    assert (
        issue_registry.async_get_issue(
            DOMAIN, f"invalid_area_ids_{entry.entry_id}"
        )
        is None
    )


@pytest.mark.parametrize("status_code", [400, 403, 429])
async def test_sepush_failure_creates_repair_issue(
    hass: HomeAssistant,
    mock_sepush: MagicMock,
    freezer: FrozenDateTimeFactory,
    status_code: int,
) -> None:
    """An auth/quota SePush failure on the stage poll raises a repair issue."""
    freezer.move_to(FROZEN_TIME)
    mock_sepush.status.side_effect = SePushError("api error", status_code=status_code)
    entry = build_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(
        DOMAIN, f"sepush_api_failure_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR


async def test_sepush_failure_issue_cleared_on_recovery(
    hass: HomeAssistant,
    mock_sepush: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A successful stage poll clears a previously raised SePush repair issue."""
    freezer.move_to(FROZEN_TIME)
    mock_sepush.status.side_effect = SePushError("quota exceeded", status_code=429)
    entry = build_config_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    issue_id = f"sepush_api_failure_{entry.entry_id}"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None

    mock_sepush.status.side_effect = None
    mock_sepush.status.return_value = STATUS_DATA
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_STAGE]
    freezer.tick(timedelta(seconds=STAGE_UPDATE_INTERVAL + 1))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_stage_coordinator_data(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The stage coordinator parses the SePush status payload."""
    entry = init_integration
    coordinator = hass.data[DOMAIN][entry.entry_id][ATTR_STAGE]
    assert "eskom" in coordinator.data
    assert coordinator.data["eskom"]["name"] == "National"
    planned = coordinator.data["eskom"]["planned"]
    assert planned[0][ATTR_STAGE] is Stage.STAGE_2


async def test_stage_coordinator_cached_within_interval(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """The stage coordinator returns cached data within the update interval."""
    entry = init_integration
    coordinator: LoadSheddingStageCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_STAGE
    ]
    coordinator.sepush.status.reset_mock()
    freezer.tick(timedelta(seconds=60))
    result = await coordinator._async_update_data()
    assert result is coordinator.data
    coordinator.sepush.status.assert_not_called()


async def test_stage_coordinator_handles_api_error(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The stage coordinator clears data and backs off on a quota error."""
    entry = init_integration
    coordinator: LoadSheddingStageCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_STAGE
    ]
    coordinator.last_update = None
    coordinator.sepush.status.side_effect = SePushError("quota", status_code=429)
    result = await coordinator._async_update_data()
    assert result == {}
    assert coordinator.last_update is not None


async def test_stage_coordinator_handles_update_failed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The stage coordinator clears data on an unexpected update failure."""
    entry = init_integration
    coordinator: LoadSheddingStageCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_STAGE
    ]
    coordinator.last_update = None
    coordinator.sepush.status.side_effect = UpdateFailed("boom")
    result = await coordinator._async_update_data()
    assert result == {}


async def test_area_coordinator_cached_within_interval(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """The area coordinator refreshes the forecast but skips the API when cached."""
    entry = init_integration
    coordinator: LoadSheddingAreaCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_AREA
    ]
    coordinator.sepush.area.reset_mock()
    freezer.tick(timedelta(seconds=60))
    result = await coordinator._async_update_data()
    assert result is coordinator.data
    coordinator.sepush.area.assert_not_called()


async def test_area_coordinator_preserves_data_on_api_error(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A transient area API error keeps the previously-fetched schedule."""
    entry = init_integration
    coordinator: LoadSheddingAreaCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_AREA
    ]
    assert AREA_ID in coordinator.data
    coordinator.last_update = None
    coordinator.sepush.area.side_effect = SePushError("boom", status_code=500)
    result = await coordinator._async_update_data()
    assert AREA_ID in result


async def test_area_forecast_from_planned_schedule(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """The forecast is derived by clipping the area schedule to planned stages."""
    freezer.move_to(FROZEN_TIME)
    entry = init_integration
    area_coordinator: LoadSheddingAreaCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ][ATTR_AREA]
    stage_coordinator = area_coordinator.stage_coordinator

    planned_start = datetime(2026, 6, 18, 7, 0, tzinfo=UTC)
    planned_end = datetime(2026, 6, 18, 22, 0, tzinfo=UTC)
    stage_coordinator.data = {
        "eskom": {
            ATTR_NAME: "National",
            ATTR_PLANNED: [
                {
                    ATTR_STAGE: Stage.STAGE_2,
                    ATTR_START_TIME: planned_start,
                    ATTR_END_TIME: planned_end,
                }
            ],
        }
    }

    slot_start = datetime(2026, 6, 18, 18, 0, tzinfo=UTC)
    slot_end = datetime(2026, 6, 18, 20, 30, tzinfo=UTC)
    area_coordinator.data = {
        AREA_ID: {
            ATTR_SCHEDULE: {
                Stage.STAGE_2: [
                    {
                        ATTR_STAGE: Stage.STAGE_2,
                        ATTR_START_TIME: slot_start,
                        ATTR_END_TIME: slot_end,
                    }
                ]
            },
            ATTR_EVENTS: [],
        }
    }

    await area_coordinator.async_area_forecast()

    forecast = area_coordinator.data[AREA_ID][ATTR_FORECAST]
    assert len(forecast) == 1
    assert forecast[0][ATTR_STAGE] is Stage.STAGE_2
    assert forecast[0][ATTR_START_TIME] == slot_start
    assert forecast[0][ATTR_END_TIME] == slot_end


@pytest.mark.parametrize(
    "note",
    [
        pytest.param("Loadshedding", id="single_word"),
        pytest.param("", id="empty"),
        pytest.param(None, id="missing"),
    ],
)
async def test_area_update_handles_malformed_event_note(
    hass: HomeAssistant, init_integration: MockConfigEntry, note: str | None
) -> None:
    """A malformed event note does not crash the area update."""
    entry = init_integration
    coordinator: LoadSheddingAreaCoordinator = hass.data[DOMAIN][entry.entry_id][
        ATTR_AREA
    ]
    coordinator.sepush.area.return_value = {
        "events": [
            {
                "note": note,
                "start": "2026-06-18T20:00:00+02:00",
                "end": "2026-06-18T22:30:00+02:00",
            }
        ],
        "schedule": {"days": []},
    }

    result = await coordinator.async_update_area()

    assert result[AREA_ID][ATTR_EVENTS][0][ATTR_STAGE] is Stage.NO_LOAD_SHEDDING



def test_utc_dt() -> None:
    """utc_dt combines a SAST date and time into a UTC datetime."""
    date = datetime(2026, 6, 18, 0, 0)
    time = datetime(1900, 1, 1, 20, 0)
    result = utc_dt(date, time)
    assert result == datetime(2026, 6, 18, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("version", "minor_version", "expected_minor"),
    [
        pytest.param(3, 1, 4, id="from_v3"),
        pytest.param(4, 1, 5, id="from_v4"),
    ],
)
async def test_migrate_entry(
    hass: HomeAssistant,
    version: int,
    minor_version: int,
    expected_minor: int,
) -> None:
    """Old config entries migrate to the current options layout."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "key"},
        options={CONF_API_KEY: "key", CONF_AREAS: {AREA_ID: {CONF_ID: AREA_ID}}},
        version=version,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 1
    assert entry.minor_version == expected_minor
    assert entry.options[CONF_API_KEY] == "key"


async def test_migrate_entry_already_latest(hass: HomeAssistant) -> None:
    """A config entry already at the latest version is not migrated."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={}, version=1, minor_version=4
    )
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)
