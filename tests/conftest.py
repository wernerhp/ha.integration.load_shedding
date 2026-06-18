"""Common fixtures and mock data for the Load Shedding integration tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.const import CONF_API_KEY, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant

from custom_components.load_shedding.const import CONF_AREAS, DOMAIN

from pytest_homeassistant_custom_component.common import MockConfigEntry

API_KEY = "test-api-key"

# A valid v3 SePush area id (underscores) and its human name.
AREA_ID = "za_gt_tsh_garsfontein_gaev"
AREA_NAME = "Garsfontein"

# A legacy v2 area id (contains hyphens) used to test the invalid-area repair flow.
LEGACY_AREA_ID = "tshwane-8-moreletapark"
LEGACY_AREA_NAME = "Moreleta Park"

# Frozen reference time used by the time-sensitive fixtures: 2026-06-18 08:00 UTC.
FROZEN_TIME = "2026-06-18T08:00:00+00:00"

# SePush ``/status`` payload. Times are in SAST (+02:00).
STATUS_DATA = {
    "status": {
        "eskom": {
            "name": "National",
            "stage": "2",
            "stage_updated": "2026-06-18T09:00:00+02:00",
            "next_stages": [
                {
                    "stage": "4",
                    "stage_start_timestamp": "2026-06-18T20:00:00+02:00",
                },
            ],
        },
        "capetown": {
            "name": "Cape Town",
            "stage": "1",
            "stage_updated": "2026-06-18T09:00:00+02:00",
            "next_stages": [],
        },
    }
}

# SePush ``/area`` payload for ``AREA_ID``. Times are in SAST (+02:00).
AREA_DATA = {
    "events": [
        {
            "note": "Stage 2",
            "start": "2026-06-18T20:00:00+02:00",
            "end": "2026-06-18T22:30:00+02:00",
        },
    ],
    "schedule": {
        "days": [
            {
                "date": "2026-06-18",
                "stages": [
                    ["00:00-02:30"],
                    ["20:00-22:30"],
                    [],
                    [],
                    [],
                    [],
                    [],
                    [],
                ],
            },
        ],
    },
}

# SePush ``/api/allowance`` payload.
ALLOWANCE_DATA = {
    "allowance": {
        "count": 5,
        "limit": 50,
        "type": "daily",
    }
}


def build_sepush_mock() -> MagicMock:
    """Return a MagicMock that mimics the SePush client used by the integration."""
    sepush = MagicMock()
    sepush.status.return_value = STATUS_DATA
    sepush.area.return_value = AREA_DATA
    sepush.check_allowance.return_value = ALLOWANCE_DATA
    return sepush


@pytest.fixture
def mock_sepush() -> Generator[MagicMock]:
    """Patch the SePush client in both the component and the config flow."""
    sepush = build_sepush_mock()
    with (
        patch(
            "custom_components.load_shedding.SePush", return_value=sepush
        ),
        patch(
            "custom_components.load_shedding.config_flow.SePush",
            return_value=sepush,
        ),
    ):
        yield sepush


def build_config_entry(
    *,
    api_key: str | None = API_KEY,
    areas: list[dict] | None = None,
    options_extra: dict | None = None,
) -> MockConfigEntry:
    """Build a MockConfigEntry for the integration."""
    if areas is None:
        areas = [{CONF_ID: AREA_ID, CONF_NAME: AREA_NAME, "description": AREA_NAME}]
    options: dict = {CONF_AREAS: areas}
    if api_key is not None:
        options[CONF_API_KEY] = api_key
    if options_extra:
        options.update(options_extra)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Load Shedding",
        data={},
        options=options,
        version=5,
    )


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a fully configured config entry."""
    return build_config_entry()


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_sepush: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """Set up the Load Shedding integration for testing."""
    freezer.move_to(FROZEN_TIME)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
