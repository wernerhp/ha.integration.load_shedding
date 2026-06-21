"""Tests for the Load Shedding config and options flows."""

from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from load_shedding.libs.sepush import SePushError
from load_shedding.providers import Area, Province, ProviderError
import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.load_shedding.config_flow import _get_sepush_status_code
from custom_components.load_shedding.const import (
    CONF_ACTION,
    CONF_ADD_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    CONF_DELETE_AREA,
    CONF_MIN_EVENT_DURATION,
    CONF_MULTI_STAGE_EVENTS,
    CONF_SEARCH,
    CONF_SETUP_API,
    DOMAIN,
)

from .conftest import API_KEY, AREA_ID, AREA_NAME, build_config_entry

from pytest_homeassistant_custom_component.common import MockConfigEntry

GET_AREAS = "custom_components.load_shedding.config_flow.get_areas"


def _areas() -> list[Area]:
    return [
        Area(
            id=AREA_ID,
            name=AREA_NAME,
            municipality="Tshwane",
            province=Province.GAUTENG.value,
        )
    ]


async def test_user_flow_full(hass: HomeAssistant, mock_sepush: MagicMock) -> None:
    """A user can complete the full config flow and create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sepush"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lookup_areas"

    with patch(GET_AREAS, return_value=_areas()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SEARCH: "garsfontein"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lookup_areas"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SEARCH: "garsfontein", CONF_AREA_ID: AREA_ID}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_API_KEY] == API_KEY
    assert result["options"][CONF_AREAS][0][CONF_ID] == AREA_ID


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        pytest.param(400, "sepush_400", id="bad_request"),
        pytest.param(403, "sepush_403", id="forbidden"),
        pytest.param(429, "sepush_429", id="rate_limited"),
        pytest.param(500, "sepush_500", id="server_error"),
    ],
)
async def test_user_flow_api_errors(
    hass: HomeAssistant,
    mock_sepush: MagicMock,
    status_code: int,
    expected: str,
) -> None:
    """API errors while validating the key surface as form errors."""
    mock_sepush.rate_limit.side_effect = SePushError(
        "boom", status_code=status_code
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_user_flow_unexpected_error(
    hass: HomeAssistant, mock_sepush: MagicMock
) -> None:
    """An unexpected error while validating the key surfaces as 'unknown'."""
    mock_sepush.rate_limit.side_effect = ValueError("boom")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sepush"
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_no_results(
    hass: HomeAssistant, mock_sepush: MagicMock
) -> None:
    """An empty area search reports a no-results error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    with patch(GET_AREAS, return_value=[]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SEARCH: "nowhere"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SEARCH: "no_results_found"}


async def test_user_flow_area_search_error(
    hass: HomeAssistant, mock_sepush: MagicMock
) -> None:
    """A provider error during area search surfaces as a form error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    error = ProviderError(SePushError("boom", status_code=403))
    with patch(GET_AREAS, side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SEARCH: "garsfontein"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sepush_403"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            ProviderError(SePushError("x", status_code=429)),
            "sepush_429",
            id="rate_limited",
        ),
        pytest.param(
            ProviderError(SePushError("x", status_code=500)),
            "sepush_500",
            id="server_error",
        ),
        pytest.param(
            ProviderError("no status code"),
            "provider_error",
            id="generic_provider_error",
        ),
    ],
)
async def test_user_flow_area_search_error_codes(
    hass: HomeAssistant,
    mock_sepush: MagicMock,
    error: ProviderError,
    expected: str,
) -> None:
    """Each area-search provider error maps to the right form error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY}
    )
    with patch(GET_AREAS, side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SEARCH: "garsfontein"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_options_flow_set_durations(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The options init step stores the event options."""
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_MULTI_STAGE_EVENTS: False, CONF_MIN_EVENT_DURATION: 45},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[CONF_MIN_EVENT_DURATION] == 45
    assert init_integration.options[CONF_MULTI_STAGE_EVENTS] is False


async def test_options_flow_add_area(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An area can be added through the options flow."""
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_ADD_AREA}
    )
    assert result["step_id"] == "lookup_areas"

    new_area = Area(
        id="za_gt_jhb_fourways_4pef",
        name="Fourways",
        municipality="Johannesburg",
        province=Province.GAUTENG.value,
    )
    with patch(GET_AREAS, return_value=[new_area]):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SEARCH: "fourways"}
        )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SEARCH: "fourways", CONF_AREA_ID: "za_gt_jhb_fourways_4pef"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    area_ids = [a[CONF_ID] for a in init_integration.options[CONF_AREAS]]
    assert "za_gt_jhb_fourways_4pef" in area_ids


async def test_options_flow_delete_area(
    hass: HomeAssistant, mock_sepush: MagicMock, freezer: FrozenDateTimeFactory
) -> None:
    """An area can be removed through the options flow (issue #111 regression)."""
    freezer.move_to("2026-06-18T08:00:00+00:00")
    entry = build_config_entry(
        areas=[
            {CONF_ID: AREA_ID, CONF_NAME: AREA_NAME, "description": AREA_NAME},
            {
                CONF_ID: "za_gt_jhb_fourways_4pef",
                CONF_NAME: "Fourways",
                "description": "Fourways",
            },
        ]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_DELETE_AREA}
    )
    assert result["step_id"] == "delete_area"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_AREA_ID: "0"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    area_ids = [a[CONF_ID] for a in entry.options[CONF_AREAS]]
    assert area_ids == ["za_gt_jhb_fourways_4pef"]


async def test_options_flow_setup_api(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The API key can be reconfigured through the options flow."""
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_SETUP_API}
    )
    assert result["step_id"] == "sepush"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[CONF_API_KEY] == "new-key"


async def test_options_flow_setup_api_unexpected_error(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sepush: MagicMock
) -> None:
    """An unexpected error while reconfiguring the key surfaces as 'unknown'."""
    mock_sepush.rate_limit.side_effect = ValueError("boom")
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_SETUP_API}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sepush"
    assert result["errors"] == {"base": "unknown"}


async def test_options_flow_add_area_no_results(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An empty area search in the options flow reports a no-results error."""
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_ADD_AREA}
    )
    with patch(GET_AREAS, return_value=[]):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SEARCH: "nowhere"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SEARCH: "no_results_found"}


async def test_options_flow_add_area_search_error(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A provider error during an options area search surfaces an error."""
    result = await hass.config_entries.options.async_init(
        init_integration.entry_id
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ACTION: CONF_ADD_AREA}
    )
    error = ProviderError(SePushError("boom", status_code=429))
    with patch(GET_AREAS, side_effect=error):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SEARCH: "garsfontein"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sepush_429"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            ProviderError(SePushError("x", status_code=429)),
            429,
            id="wrapped_in_args",
        ),
        pytest.param(ValueError("no status here"), None, id="unrelated_error"),
    ],
)
def test_get_sepush_status_code(error: BaseException, expected: int | None) -> None:
    """The status-code helper walks the exception chain for a SePushError."""
    assert _get_sepush_status_code(error) == expected


def test_get_sepush_status_code_from_cause() -> None:
    """The helper finds a SePushError chained via ``raise ... from``."""
    cause = SePushError("boom", status_code=500)
    err = ProviderError("wrapped")
    err.__cause__ = cause
    assert _get_sepush_status_code(err) == 500
