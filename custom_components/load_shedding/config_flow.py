"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

from load_shedding.providers.provider import ProviderError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_SUBURB, CONF_SUBURB_ID, DOMAIN, PROVIDER

_LOGGER = logging.getLogger(__name__)


def find_suburbs(suburb: str) -> str | None:
    """Search a suburb."""
    _LOGGER.debug("Searching '%s'", suburb)

    try:
        provider = PROVIDER()
        suburbs = provider.find_suburbs(search_text=suburb, max_results=25)
    except ProviderError as e:
        return e
    else:
        return suburbs


@config_entries.HANDLERS.register(DOMAIN)
class LoadSheddingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for LoadShedding."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_search(user_input)

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow to search for a suburb."""
        errors = {}

        if user_input is not None:
            search = user_input.get(CONF_SUBURB)
            suburb_id = user_input.get(CONF_SUBURB_ID)

            if suburb_id is None:
                try:
                    results = await self.hass.async_add_executor_job(
                        find_suburbs, search
                    )
                except ProviderError as e:
                    _LOGGER.exception(f"{e}")
                    errors["base"] = "unknown"
                else:
                    suburbs = {}
                    suburb_ids = {}
                    for suburb in results:
                        suburbs[suburb.id] = suburb

                        suburb_ids[
                            suburb.id
                        ] = "{suburb}, {municipality}, {province}".format(
                            suburb=suburb.name,
                            municipality=suburb.municipality.name,
                            province=suburb.province,
                        )

                    self.suburbs = suburbs
                    data_schema = vol.Schema(
                        {
                            vol.Required(CONF_SUBURB, default=search): str,
                            vol.Optional(CONF_SUBURB_ID): vol.In(suburb_ids),
                        }
                    )
                return self.async_show_form(
                    step_id="search",
                    data_schema=data_schema,
                    errors=errors,
                )

            elif suburb_id is not None:
                suburb = self.suburbs.get(suburb_id)

                if not errors:
                    description = "{suburb}, {municipality}, {province}".format(
                        suburb=suburb.name,
                        municipality=suburb.municipality.name,
                        province=suburb.province,
                    )
                    data = {
                        "description": description,
                        "suburb": suburb.name,
                        "suburb_id": suburb.id,
                        "municipality": suburb.municipality.name,
                        "province": str(suburb.province),
                        "province_id": suburb.province.value,
                    }
                    return self.async_create_entry(
                        title=description,
                        data=data,
                        description="Load Shedding configuration",
                    )

                await self.async_set_unique_id(suburb.id, raise_on_progress=False)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SUBURB): str,
            }
        )
        return self.async_show_form(
            step_id="search",
            data_schema=data_schema,
            errors=errors,
        )
