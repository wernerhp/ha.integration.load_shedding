"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult, RESULT_TYPE_SHOW_PROGRESS_DONE

from load_shedding import load_shedding

from load_shedding.providers import Area, ProviderError
from .const import (
    CONF_PROVIDER,
    CONF_AREAS,
    CONF_AREA_ID,
    CONF_SEARCH,
    CONF_STAGE,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


def load_provider(name: str) -> load_shedding.Provider:
    """Load a provider from module name"""
    providers = load_shedding.get_providers()
    for provider in providers:
        if str(provider.__class__) == name:
            return provider

    return Exception(f"No provider found: {name}")


def get_areas(p: load_shedding.Provider, search_text: str) -> list[Area]:
    """Search a area."""
    try:
        provider = p.load()
        _LOGGER.debug("Searching %s for %s", provider.name, search_text)
        areas = load_shedding.get_areas(
            provider, search_text=search_text, max_results=25
        )
        _LOGGER.debug("Found %d results", len(areas))
    except ProviderError:
        _LOGGER.debug("Provider error", exc_info=True)
        raise
    except Exception as e:
        _LOGGER.debug("Unknown exception", exc_info=True)
        raise ProviderError(e)
    else:
        return areas


@config_entries.HANDLERS.register(DOMAIN)
class LoadSheddingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for LoadShedding."""

    VERSION = 1

    def __init__(self):
        self.provider: load_shedding.Provider = None
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
        for provider in load_shedding.get_providers():
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
        self.provider = load_shedding.Provider(user_input.get(CONF_PROVIDER))
        if not user_input.get(CONF_AREA_ID):
            try:
                results = await self.hass.async_add_executor_job(
                    get_areas, self.provider, search_text
                )
            except ProviderError:
                _LOGGER.debug("Provider error", exc_info=True)
                errors["base"] = "provider_error"
            else:
                self.areas = {}
                area_ids = {}
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
                "provider": self.provider.value,
            },
            CONF_AREAS: [
                {
                    "description": description,
                    "area": area.name,
                    "area_id": area.id,
                    "municipality": area.municipality,
                    "provider": self.provider.value,
                    "province": str(area.province),
                    "province_id": area.province.value,
                }
            ],
        }
        _LOGGER.debug("Config entry: %s", data)

        entry = await self.async_set_unique_id(f"{DOMAIN}")
        if entry:
            try:
                _LOGGER.debug("Entry exists: %s", entry)
                if self.hass.config_entries.async_update_entry(entry, data=data):
                    await self.hass.config_entries.async_reload(entry.entry_id)
            except Exception:
                _LOGGER.debug("Unknown error", exc_info=True)
                raise
            else:
                return self.async_abort(reason=RESULT_TYPE_SHOW_PROGRESS_DONE)

        return self.async_create_entry(
            title=f"{NAME}",
            data=data,
            description="Load Shedding configuration",
        )
