"""Adds config flow for LoadShedding."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_DESCRIPTION, CONF_ID, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, FlowHandler

from load_shedding import Provider, Province, get_areas
from load_shedding.libs.sepush import SePush, SePushError
from load_shedding.providers import ProviderError, Stage
from .const import (
    CONF_AREA_ID,
    CONF_AREAS,
    CONF_PROVIDER,
    CONF_SEARCH,
    DOMAIN,
    NAME,
    CONF_ACTION,
    CONF_ADD_AREA,
    CONF_DELETE_AREA,
    CONF_MULTI_STAGE_EVENTS,
    CONF_SETUP_API,
)

_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register(DOMAIN)
class LoadSheddingFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for LoadShedding."""

    VERSION = 4

    def __init__(self):
        self.provider: Provider = None
        self.api_key: str = ""
        self.areas: dict = {}
        # self.device_unique_id = f"{DOMAIN}"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LoadSheddingOptionsFlowHandler(config_entry)

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Return options flow support for this handler."""
        return True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""

        await self._async_handle_discovery_without_unique_id()
        return await self.async_step_sepush()

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
                status_code = err.__cause__.args[0]
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

        data = {}
        options = {
            CONF_API_KEY: self.api_key,
            CONF_AREAS: {
                area.id: {
                    CONF_DESCRIPTION: description,
                    CONF_NAME: area.name,
                    CONF_ID: area.id,
                },
            },
        }

        # entry = await self.async_set_unique_id(DOMAIN)
        # if entry:
        #     try:
        #         _LOGGER.debug("Entry exists: %s", entry)
        #         if self.hass.config_entries.async_update_entry(entry, data=data):
        #             await self.hass.config_entries.async_reload(entry.entry_id)
        #     except Exception:
        #         _LOGGER.debug("Unknown error", exc_info=True)
        #         raise
        #     else:
        #         return self.async_abort(reason=FlowResultType.SHOW_PROGRESS_DONE)

        return self.async_create_entry(
            title=NAME,
            data=data,
            description="Load Shedding configuration",
            options=options,
        )


class LoadSheddingOptionsFlowHandler(OptionsFlow):
    """Load Shedding config flow options handler."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        # self.config_entry: ConfigEntry = config_entry
        self.opts = dict(config_entry.options)

        self.provider = Provider.SE_PUSH
        self.api_key = config_entry.options.get(CONF_API_KEY)
        self.areas = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:  # pylint: disable=unused-argument
        """Manage the options."""

        CONF_ACTIONS = {
            CONF_SETUP_API: "Configure API",
            # CONF_ADD_AREA: "Add area",
            # CONF_DELETE_AREA: "Remove area",
            # CONF_MULTI_STAGE_EVENTS: ""
        }

        OPTIONS_SCHEMA = vol.Schema(
            {
                vol.Optional(CONF_ACTION): vol.In(CONF_ACTIONS),
                vol.Optional(
                    CONF_MULTI_STAGE_EVENTS,
                    default=self.opts.get(CONF_MULTI_STAGE_EVENTS, False),
                ): bool,
            }
        )

        if user_input is not None:
            if user_input.get(CONF_ACTION) == CONF_SETUP_API:
                return await self.async_step_sepush()
            if user_input.get(CONF_ACTION) == CONF_ADD_AREA:
                return await self.async_step_add_area()
            # if user_input.get(CONF_ACTION) == CONF_DELETE_AREA:
            #     return await self.async_step_delete_area()
            self.opts[CONF_MULTI_STAGE_EVENTS] = user_input.get(CONF_MULTI_STAGE_EVENTS)
            return self.async_create_entry(title=NAME, data=self.opts)

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_SCHEMA,
        )

    async def async_step_sepush(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to configure SePush."""
        self.provider = Provider.SE_PUSH

        if not user_input:
            user_input = {}

        api_key = user_input.get(CONF_API_KEY)
        errors = {}
        if api_key:
            try:
                # Validate the token by checking the allowance.
                sepush = SePush(token=api_key)
                esp = await self.hass.async_add_executor_job(sepush.check_allowance)
                _LOGGER.debug("Validate API Key Response: %s", esp)
            except (SePushError) as err:
                status_code = err.__cause__.args[0]
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
                self.api_key = api_key
                self.opts[CONF_API_KEY] = api_key
                return self.async_create_entry(title=NAME, data=self.opts)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY, default=self.api_key): str,
            }
        )
        return self.async_show_form(
            step_id="sepush",
            data_schema=data_schema,
            errors=errors,
        )

    # async def async_step_init(
    #     self, user_input: dict[str, Any] | None = None
    # ) -> FlowResult:  # pylint: disable=unused-argument
    #     """Manage the options."""

    #     CONF_ACTIONS = {
    #         CONF_ADD_DEVICE: "Add Area",
    #         CONF_EDIT_DEVICE: "Remove Area",
    #     }

    #     CONFIGURE_SCHEMA = vol.Schema(
    #         {
    #             vol.Required(CONF_ACTION, default=CONF_ADD_DEVICE): vol.In(
    #                 CONF_ACTIONS
    #             ),
    #         }
    #     )

    #     return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    #     schema: dict[vol.Marker, type] = {}
    #     areas = self.opts.get(CONF_AREAS, {})
    #     for area_id, area in areas.items():
    #         schema[vol.Required(area_id, default=True)] = vol.In(
    #             {area_id: area.get(CONF_DESCRIPTION)}
    #         )

    #     return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    #     return await self.async_step_lookup_areas()

    async def async_step_add_area(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow step to search for and select an area."""
        return await self.async_step_lookup_areas(user_input=user_input)

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
        areas = self.opts.get(CONF_AREAS, {})
        area = self.areas.get(user_input.get(CONF_AREA_ID))

        description = f"{area.name}"
        if area.municipality:
            description += f", {area.municipality}"
        if area.province is not Province.UNKNOWN:
            description += f", {area.province}"

        areas[area.id] = {
            CONF_DESCRIPTION: description,
            CONF_NAME: area.name,
            CONF_ID: area.id,
        }

        self.opts.update(
            {
                CONF_AREAS: areas,
            }
        )
        result = self.async_create_entry(title=NAME, data=self.opts)
        return result
