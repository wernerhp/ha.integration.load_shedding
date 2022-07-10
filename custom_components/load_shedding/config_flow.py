"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_DESCRIPTION
from homeassistant.data_entry_flow import FlowResult, FlowResultType

from load_shedding import get_areas, Provider
from load_shedding.providers import ProviderError
from .const import (
    CONF_AREA,
    CONF_AREAS,
    CONF_AREA_ID,
    CONF_PROVINCE_ID,
    CONF_PROVIDER,
    CONF_SEARCH,
    CONF_STAGE,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


def load_provider(name: str) -> Provider | Exception:
    """Load a provider from module name"""
    for provider in list(Provider):
        if str(provider.__class__) == name:
            return provider

    return Exception(f"No provider found: {name}")


@config_entries.HANDLERS.register(DOMAIN)
class LoadSheddingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for LoadShedding."""

    VERSION = 1

    def __init__(self):
        self.provider: Provider = Provider.ESKOM
        self.areas: dict = {}

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_lookup_areas(user_input)

    async def async_step_lookup_areas(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for and select an area."""
        errors = {}
        providers = {}
        default_provider = None
        for provider in list(Provider):
            if not default_provider:
                default_provider = provider.value
            providers[provider.value] = f"{provider}"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PROVIDER, default=default_provider): vol.In(
                    providers
                ),
                vol.Required(CONF_SEARCH): str,
            }
        )

        if not user_input:
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        if not user_input.get(CONF_PROVIDER):
            errors["base"] = "no_provider"
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PROVIDER, default=user_input.get(CONF_PROVIDER)
                ): vol.In(providers),
                vol.Required(CONF_SEARCH, default=user_input.get(CONF_SEARCH)): str,
            }
        )

        search_text = user_input.get(CONF_SEARCH)
        self.provider = Provider(user_input.get(CONF_PROVIDER))
        if not user_input.get(CONF_AREA_ID):
            area_ids = {}
            try:
                results = await self.hass.async_add_executor_job(
                    get_areas, self.provider(), search_text
                )
            except ProviderError:
                _LOGGER.debug("Provider error", exc_info=True)
                errors["base"] = "provider_error"
            else:
                self.areas = {}
                for area in results:
                    self.areas[area.id] = area
                    area_ids[
                        area.id
                    ] = f"{area.name}, {area.municipality}, {area.province}"

                if not self.areas:
                    errors[CONF_SEARCH] = "no_results_found"

            if not errors:
                data_schema = vol.Schema(
                    {
                        vol.Required(
                            CONF_PROVIDER, default=user_input.get(CONF_PROVIDER)
                        ): vol.In(providers),
                        vol.Required(
                            CONF_SEARCH, default=user_input.get(CONF_SEARCH)
                        ): str,
                        vol.Optional(CONF_AREA_ID): vol.In(area_ids),
                    }
                )

            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        return await self.async_step_select_area(user_input)

    async def async_step_select_area(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to create a area."""
        area_id = user_input.get(CONF_AREA_ID)
        area = self.areas.get(area_id)

        description = f"{area.name}, {area.municipality}, {area.province}"
        data = {
            CONF_STAGE: {
                CONF_PROVIDER: self.provider.value,
            },
            CONF_AREAS: [
                {
                    CONF_DESCRIPTION: description,
                    CONF_AREA: area.name,
                    CONF_AREA_ID: area.id,
                    CONF_PROVIDER: self.provider.value,
                    CONF_PROVINCE_ID: area.province.value,
                }
            ],
        }
        _LOGGER.debug("Config entry: %s", data)

        entry = await self.async_set_unique_id(DOMAIN)
        if entry:
            try:
                _LOGGER.debug("Entry exists: %s", entry)
                if self.hass.config_entries.async_update_entry(entry, data=data):
                    await self.hass.config_entries.async_reload(entry.entry_id)
            except Exception:
                _LOGGER.debug("Unknown error", exc_info=True)
                raise
            else:
                return self.async_abort(reason=FlowResultType.SHOW_PROGRESS_DONE)

        return self.async_create_entry(
            title=NAME,
            data=data,
            description="Load Shedding configuration",
        )
