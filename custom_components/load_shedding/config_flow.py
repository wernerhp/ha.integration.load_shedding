"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult, RESULT_TYPE_SHOW_PROGRESS_DONE

from load_shedding.load_shedding import Provider, get_providers, search
from load_shedding.providers import Suburb, ProviderError
from .const import (
    CONF_PROVIDER,
    CONF_SUBURBS,
    CONF_SUBURB,
    CONF_SUBURB_ID,
    CONF_STAGE,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)


def load_provider(name: str) -> Provider:
    """Load a provider from module name"""
    providers = get_providers()
    for provider in providers:
        if str(provider.__class__) == name:
            return provider

    return Exception(f"No provider found: {name}")


def suburb_search(provider: Provider, search_text: str) -> list[Suburb]:
    """Search a suburb."""
    try:
        _LOGGER.debug("Searching %s for %s", provider.name, search_text)
        suburbs = search(provider, search_text=search_text, max_results=25)
        _LOGGER.debug("Found %d results", len(suburbs))
    except ProviderError:
        _LOGGER.error("Provider error", exc_info=True)
        raise
    except Exception:
        _LOGGER.error("Unknown exception", exc_info=True)
        raise
    else:
        return suburbs


@config_entries.HANDLERS.register(DOMAIN)
class LoadSheddingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for LoadShedding."""

    VERSION = 1

    def __init__(self):
        self.provider: Provider = None
        self.suburbs: dict = {}

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_search(user_input)

    async def async_step_search(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for a suburb."""
        errors = {}
        providers = {}
        default_provider = None
        for provider in get_providers():
            if not default_provider:
                default_provider = f"{provider.__class__}"
            providers[f"{provider.__class__}"] = f"{provider.name}"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PROVIDER, default=default_provider): vol.In(
                    providers
                ),
                vol.Required(CONF_SUBURB): str,
            }
        )

        if not user_input:
            return self.async_show_form(
                step_id="search",
                data_schema=data_schema,
                errors=errors,
            )

        if not user_input.get(CONF_PROVIDER):
            errors["base"] = "no_provider"
            return self.async_show_form(
                step_id="search",
                data_schema=data_schema,
                errors=errors,
            )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PROVIDER, default=user_input.get(CONF_PROVIDER)
                ): vol.In(providers),
                vol.Required(CONF_SUBURB, default=user_input.get(CONF_SUBURB)): str,
            }
        )

        search_text = user_input.get(CONF_SUBURB)
        self.provider = load_provider(user_input.get(CONF_PROVIDER))
        if not user_input.get(CONF_SUBURB_ID):
            try:
                results = await self.hass.async_add_executor_job(
                    suburb_search, self.provider, search_text
                )
            except ProviderError:
                _LOGGER.error("Provider error", exc_info=True)
                errors["base"] = "provider_error"
            else:
                self.suburbs = {}
                suburb_ids = {}
                for suburb in results:
                    if not suburb.total:
                        continue

                    self.suburbs[suburb.id] = suburb
                    suburb_ids[
                        suburb.id
                    ] = f"{suburb.name}, {suburb.municipality.name}, {suburb.province}"

                if not self.suburbs:
                    errors[CONF_SUBURB] = "no_results_found"

            if not errors:
                data_schema = vol.Schema(
                    {
                        vol.Required(
                            CONF_PROVIDER, default=user_input.get(CONF_PROVIDER)
                        ): vol.In(providers),
                        vol.Required(
                            CONF_SUBURB, default=user_input.get(CONF_SUBURB)
                        ): str,
                        vol.Optional(CONF_SUBURB_ID): vol.In(suburb_ids),
                    }
                )

            return self.async_show_form(
                step_id="search",
                data_schema=data_schema,
                errors=errors,
            )

        # Suburb ID selected
        return await self.async_step_suburb(user_input)

    async def async_step_suburb(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to create a suburb."""
        suburb_id = user_input.get(CONF_SUBURB_ID)
        suburb = self.suburbs.get(suburb_id)

        description = f"{suburb.name}, {suburb.municipality.name}, {suburb.province}"
        data = {
            CONF_STAGE: {
                "provider": f"{self.provider.__class__.__module__}.{self.provider.__class__.__name__}",
            },
            CONF_SUBURBS: [
                {
                    "description": description,
                    "suburb": suburb.name,
                    "suburb_id": suburb.id,
                    "municipality": suburb.municipality.name,
                    "provider": f"{self.provider.__class__.__module__}.{self.provider.__class__.__name__}",
                    "province": str(suburb.province),
                    "province_id": suburb.province.value,
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
                _LOGGER.error("Unknown error", exc_info=True)
                raise
            else:
                return self.async_abort(reason=RESULT_TYPE_SHOW_PROGRESS_DONE)

        return self.async_create_entry(
            title=f"{NAME}",
            data=data,
            description="Load Shedding configuration",
        )
