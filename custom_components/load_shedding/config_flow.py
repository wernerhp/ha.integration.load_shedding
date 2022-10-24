"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_DESCRIPTION
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, FlowResultType

from load_shedding.libs.sepush import SePush, SePushError
from load_shedding import get_areas, Province, Provider
from load_shedding.providers import ProviderError, Stage
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

    VERSION = 3

    def __init__(self):
        self.provider: Provider = None
        self.api_key: str = ""
        # self.coct_stage: bool = False
        self.areas: dict = {}

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry) -> OptionsFlow:
    #     return LoadSheddingOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_sepush(None)

    async def async_step_provider(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for and select an area."""
        errors = {}
        providers = {}

        if not user_input:
            user_input = {}

        # Provider
        if user_input and user_input.get(CONF_PROVIDER):
            self.provider = Provider(user_input.get(CONF_PROVIDER))
        default_provider = self.provider.value if self.provider else None
        for provider in list(Provider):
            if not default_provider:
                default_provider = provider.value
            providers[provider.value] = f"{provider}"

        data_schema = vol.Schema({})

        if not self.provider:
            data_schema = data_schema.extend(
                {
                    vol.Required(CONF_PROVIDER, default=default_provider): vol.In(
                        providers
                    ),
                }
            )

        if data_schema.schema:
            return self.async_show_form(
                step_id="provider",
                data_schema=data_schema,
                errors=errors,
            )

        if self.provider == Provider.SE_PUSH:
            return await self.async_step_sepush(None)

        return await self.async_step_lookup_areas(user_input)

    async def async_step_sepush(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to configure SePush."""
        self.provider = Provider.SE_PUSH
        errors = {}
        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
            }
        )

        if not user_input:
            user_input = {}

        # API Key
        self.api_key = user_input.get(CONF_API_KEY, "")

        if self.api_key:
            try:
                # Validate the token by checking the allowance.
                sepush = SePush(token=self.api_key)
                await self.hass.async_add_executor_job(sepush.check_allowance)
            except (SePushError) as err:
                status_code = err.args[1]
                if status_code == 400:
                    errors["base"] = "sepush_400"
                elif status_code == 403:
                    errors["base"] = "sepush_403"
                elif status_code == 429:
                    errors["base"] = "sepush_429"
                elif status_code == 500:
                    errors["base"] = "sepush_500"
                else:
                    errors["base"] = "provider_error"
            else:
                return await self.async_step_lookup_areas(user_input)

        return self.async_show_form(
            step_id="sepush",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_lookup_areas(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for and select an area."""
        errors = {}

        stages = {}
        for stage in [
            Stage.STAGE_1,
            Stage.STAGE_2,
            Stage.STAGE_3,
            Stage.STAGE_4,
            Stage.STAGE_5,
            Stage.STAGE_6,
            Stage.STAGE_7,
            Stage.STAGE_8,
        ]:
            stages[stage.value] = f"{stage}"
        data_schema = vol.Schema(
            {
                vol.Required(CONF_SEARCH): str,
            }
        )

        if not user_input:
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SEARCH, default=user_input.get(CONF_SEARCH)): str,
            }
        )

        search_text = user_input.get(CONF_SEARCH)
        if not search_text:
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        if not user_input.get(CONF_AREA_ID):
            area_ids = {}
            try:
                provider = self.provider(token=self.api_key)
                results = await self.hass.async_add_executor_job(
                    get_areas, provider, search_text
                )
            except ProviderError:
                _LOGGER.debug("Provider error", exc_info=True)
                errors["base"] = "provider_error"
            else:
                self.areas = {}
                for area in results:
                    self.areas[area.id] = area

                    area_ids[area.id] = f"{area.name}"

                    if area.municipality:
                        area_ids[area.id] += f", {area.municipality}"
                    if area.province is not Province.UNKNOWN:
                        area_ids[area.id] += f", {area.province}"

                if not self.areas:
                    errors[CONF_SEARCH] = "no_results_found"

            if not errors:
                data_schema = vol.Schema(
                    {
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

        description = f"{area.name}"

        if area.municipality:
            description += f", {area.municipality}"
        if area.province is not Province.UNKNOWN:
            description += f", {area.province}"

        data = {
            CONF_API_KEY: self.api_key,
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


class LoadSheddingOptionsFlowHandler(OptionsFlow):
    """Load Shedding config flow options handler."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

        self.provider = Provider.SE_PUSH
        self.api_key = config_entry.data.get(CONF_API_KEY)

    async def async_step_init(
        self, user_input=None
    ) -> FlowResult:  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_lookup_areas()

    async def async_step_lookup_areas(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for and select an area."""
        errors = {}

        stages = {}
        for stage in [
            Stage.STAGE_1,
            Stage.STAGE_2,
            Stage.STAGE_3,
            Stage.STAGE_4,
            Stage.STAGE_5,
            Stage.STAGE_6,
            Stage.STAGE_7,
            Stage.STAGE_8,
        ]:
            stages[stage.value] = f"{stage}"
        data_schema = vol.Schema(
            {
                vol.Required(CONF_SEARCH): str,
            }
        )

        if not user_input:
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SEARCH, default=user_input.get(CONF_SEARCH)): str,
            }
        )

        search_text = user_input.get(CONF_SEARCH)
        if not search_text:
            return self.async_show_form(
                step_id="lookup_areas",
                data_schema=data_schema,
                errors=errors,
            )

        if not user_input.get(CONF_AREA_ID):
            area_ids = {}
            try:
                provider = self.provider(token=self.api_key)
                results = await self.hass.async_add_executor_job(
                    get_areas, provider, search_text
                )
            except ProviderError:
                _LOGGER.debug("Provider error", exc_info=True)
                errors["base"] = "provider_error"
            else:
                self.areas = {}
                for area in results:
                    self.areas[area.id] = area

                    area_ids[area.id] = f"{area.name}"

                    if area.municipality:
                        area_ids[area.id] += f", {area.municipality}"
                    if area.province is not Province.UNKNOWN:
                        area_ids[area.id] += f", {area.province}"

                if not self.areas:
                    errors[CONF_SEARCH] = "no_results_found"

            if not errors:
                data_schema = vol.Schema(
                    {
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

        description = f"{area.name}"

        if area.municipality:
            description += f", {area.municipality}"
        if area.province is not Province.UNKNOWN:
            description += f", {area.province}"

        data = {
            CONF_API_KEY: self.api_key,
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

        return self.async_create_entry(
            title=NAME,
            data=data,
            description="Load Shedding configuration",
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(title=NAME, data=self.options)
