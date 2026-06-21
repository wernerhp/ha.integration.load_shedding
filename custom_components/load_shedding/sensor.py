"""Support for the LoadShedding service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from load_shedding.libs.sepush import SePushError
from load_shedding.providers import Area, Stage

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    RestoreSensor,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ATTRIBUTION, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LoadSheddingDevice
from .helpers import (
    build_sensor_attrs,
    filter_restorable_attrs,
    is_load_shedding_active,
    merge_forecast,
    rehydrate_restored_datetimes,
)
from .const import (
    ATTR_AREA,
    ATTR_AREA_ID,
    ATTR_END_IN,
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_FORECAST_CALENDAR,
    ATTR_LAST_UPDATE,
    ATTR_NEXT_END_TIME,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_PLANNED,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_START_IN,
    ATTR_START_TIME,
    ATTRIBUTION,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_DATA = {
    ATTR_STAGE: Stage.NO_LOAD_SHEDDING.value,
    ATTR_START_TIME: 0,
    ATTR_END_TIME: 0,
    ATTR_END_IN: 0,
    ATTR_START_IN: 0,
    ATTR_NEXT_STAGE: Stage.NO_LOAD_SHEDDING.value,
    ATTR_NEXT_START_TIME: 0,
    ATTR_NEXT_END_TIME: 0,
    ATTR_PLANNED: [],
    ATTR_FORECAST: [],
    ATTR_SCHEDULE: [],
    ATTR_LAST_UPDATE: None,
    ATTR_ATTRIBUTION: ATTRIBUTION.format(provider="sepush.co.za"),
}

CLEAN_DATA = {
    ATTR_PLANNED: [],
    ATTR_FORECAST: [],
    ATTR_FORECAST_CALENDAR: [],
    ATTR_SCHEDULE: [],
}

# Data-bearing attributes restored after a restart so the forecast/schedule
# survive an API outage (e.g. an exhausted daily quota) until the first
# successful poll, instead of disappearing (#31). Reserved/entity-managed
# attributes (friendly_name, icon, unit, ...) are deliberately excluded.
RESTORABLE_ATTRS = (
    ATTR_STAGE,
    ATTR_START_TIME,
    ATTR_END_TIME,
    ATTR_END_IN,
    ATTR_START_IN,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_NEXT_END_TIME,
    ATTR_PLANNED,
    ATTR_FORECAST,
    ATTR_FORECAST_CALENDAR,
    ATTR_SCHEDULE,
    ATTR_AREA_ID,
)


def restorable_attrs(last_state) -> dict:
    """Return the data-bearing attributes worth restoring after a restart."""
    attributes = last_state.attributes if last_state is not None else {}
    restored = filter_restorable_attrs(attributes, RESTORABLE_ATTRS)
    return rehydrate_restored_datetimes(restored)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    coordinators = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    stage_coordinator = coordinators.get(ATTR_STAGE)
    area_coordinator = coordinators.get(ATTR_AREA)
    known_providers: set[str] = set()

    @callback
    def _async_add_stage_entities() -> None:
        """Create stage entities for newly seen providers.

        Providers are discovered from the SePush status payload, so when the
        first poll is empty (e.g. the API quota is exhausted at startup) the
        entities are created later, once data arrives (M2).
        """
        new = [idx for idx in stage_coordinator.data if idx not in known_providers]
        if not new:
            return
        known_providers.update(new)
        async_add_entities(
            LoadSheddingStageSensorEntity(stage_coordinator, idx) for idx in new
        )

    entry.async_on_unload(
        stage_coordinator.async_add_listener(_async_add_stage_entities)
    )
    _async_add_stage_entities()

    entities: list[Entity] = []
    for area in area_coordinator.areas:
        area_entity = LoadSheddingAreaSensorEntity(area_coordinator, area)
        entities.append(area_entity)

    # Quota sensor subscribes to the stage coordinator — the stage poll (status)
    # populates sepush.rate_limit() as a side-effect, so no dedicated quota call
    # is ever needed.
    quota_entity = LoadSheddingQuotaSensorEntity(stage_coordinator)
    entities.append(quota_entity)

    async_add_entities(entities)


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""


class LoadSheddingStageSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Stage entity."""

    def __init__(self, coordinator: CoordinatorEntity, idx: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.idx = idx
        self.data = self.coordinator.data.get(self.idx)

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_{self.idx}"
        self.entity_id = f"{SENSOR_DOMAIN}.{DOMAIN}_stage_{idx}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        # Restore last known attributes so the planned schedule survives a
        # restart while the API quota is exhausted, until the first poll (#31).
        if attrs := restorable_attrs(await self.async_get_last_state()):
            if not hasattr(self, "_attr_extra_state_attributes"):
                self._attr_extra_state_attributes = {}
            if not self._attr_extra_state_attributes:
                self._attr_extra_state_attributes = attrs
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        """Return the stage sensor name."""
        name = self.data.get("name", "Unknown")
        return f"{name} Stage"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if not self.data:
            return self._attr_native_value

        planned = self.data.get(ATTR_PLANNED, [])
        if not planned:
            return Stage.NO_LOAD_SHEDDING

        stage = planned[0].get(ATTR_STAGE, Stage.NO_LOAD_SHEDDING)

        self._attr_native_value = cast(StateType, stage)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        self.data = self.coordinator.data.get(self.idx)
        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(UTC)
        # Rebuild the planned list from live coordinator data unconditionally so
        # stale entries (and derived next_*/ends_in fields) are dropped when the
        # planned list empties (C2).
        planned = []
        for event in self.data.get(ATTR_PLANNED, []):
            if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                continue

            entry = {
                ATTR_STAGE: event.get(ATTR_STAGE),
                ATTR_START_TIME: event.get(ATTR_START_TIME),
            }
            if ATTR_END_TIME in event:
                entry[ATTR_END_TIME] = event.get(ATTR_END_TIME)

            planned.append(entry)

        cur_stage = Stage.NO_LOAD_SHEDDING
        if planned:
            cur_stage = planned[0].get(ATTR_STAGE, Stage.NO_LOAD_SHEDDING)

        attrs = get_sensor_attrs(planned, cur_stage)
        attrs[ATTR_PLANNED] = planned
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes = attrs
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data.get(self.idx)
            # Explicitly get the native value to force state update
            self._attr_native_value = self.native_value
            self.async_write_ha_state()


class LoadSheddingAreaSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Area sensor entity."""

    def __init__(self, coordinator: CoordinatorEntity, area: Area) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.area = area
        self.data = self.coordinator.data.get(self.area.id)

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {area.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} schedule {area.name}",
            entity_registry_enabled_default=True,
        )
        self._attr_unique_id = (
            f"{self.coordinator.config_entry.entry_id}_sensor_{area.id}"
        )
        self.entity_id = f"{SENSOR_DOMAIN}.{DOMAIN}_area_{area.id.replace('-', '_')}"

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        # Restore last known attributes so the forecast/schedule survive a
        # restart while the API quota is exhausted, until the first poll (#31).
        if attrs := restorable_attrs(await self.async_get_last_state()):
            if not hasattr(self, "_attr_extra_state_attributes"):
                self._attr_extra_state_attributes = {}
            if not self._attr_extra_state_attributes:
                self._attr_extra_state_attributes = attrs
        await super().async_added_to_hass()

    @property
    def name(self) -> str | None:
        """Return the area sensor name."""
        return self.area.name

    @property
    def native_value(self) -> StateType:
        """Return the area state."""
        if not self.data:
            return self._attr_native_value

        events = self.data.get(ATTR_FORECAST, [])
        now = datetime.now(UTC)

        # Default to OFF; only ON for a currently-active event. Guarantees the
        # state clears when load shedding ends (#103/#104).
        state = STATE_ON if is_load_shedding_active(events, now) else STATE_OFF
        self._attr_native_value = cast(StateType, state)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        if not self.data:
            return self._attr_extra_state_attributes

        now = datetime.now(UTC)
        # Rebuild the forecast from live coordinator data unconditionally so
        # stale events (and derived next_*/ends_in fields) are dropped when the
        # forecast empties at the end of load shedding (C2).
        forecast = []
        for event in self.data.get(ATTR_FORECAST, []):
            if ATTR_END_TIME in event and event.get(ATTR_END_TIME) < now:
                continue

            forecast.append(
                {
                    ATTR_STAGE: event.get(ATTR_STAGE),
                    ATTR_START_TIME: event.get(ATTR_START_TIME),
                    ATTR_END_TIME: event.get(ATTR_END_TIME),
                }
            )

        attrs = get_sensor_attrs(forecast, merge_contiguous=True)
        attrs[ATTR_AREA_ID] = self.area.id
        attrs[ATTR_FORECAST] = forecast
        attrs[ATTR_FORECAST_CALENDAR] = merge_forecast(forecast)
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes = attrs
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if data := self.coordinator.data:
            self.data = data.get(self.area.id)
            # Explicitly get the native value to force state update
            self._attr_native_value = self.native_value
            self.async_write_ha_state()


class LoadSheddingQuotaSensorEntity(
    LoadSheddingDevice, CoordinatorEntity, RestoreSensor
):
    """Define a LoadShedding Quota entity.

    Subscribes to the stage coordinator. When the stage poll fires (calling
    ``sepush.status()``), the SePush client caches the ``x-ratelimit-*`` response
    headers. This sensor reads that cache via ``coordinator.sepush.rate_limit()``
    — no additional API call is ever made.
    """

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        """Initialize the quota sensor."""
        super().__init__(coordinator)

        self.entity_description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} SePush Quota",
            icon="mdi:api",
            name=f"{DOMAIN} SePush Quota",
            entity_registry_enabled_default=True,
        )
        self._attr_name = f"{NAME} SePush Quota"
        self._attr_unique_id = f"{self.coordinator.config_entry.entry_id}_se_push_quota"
        self.entity_id = f"{SENSOR_DOMAIN}.{DOMAIN}_sepush_api_quota"

    def _quota(self) -> dict:
        """Return the current quota snapshot (pure cache read, no I/O)."""
        rate_limit = self._rate_limit()
        return {
            "count": rate_limit.get("used") or 0,
            "limit": rate_limit.get("limit") or 0,
            "remaining": rate_limit.get("remaining"),
            "reset": rate_limit.get("reset"),
            "type": "daily",
        }

    def _rate_limit(self) -> dict:
        """Read the cached SePush rate-limit snapshot.

        A transient API error here must not break the entity state update; the
        outage itself is surfaced as a Repairs issue by the stage coordinator.
        """
        try:
            return self.coordinator.sepush.rate_limit() or {}
        except SePushError as err:
            _LOGGER.debug("Unable to read SePush quota: %s", err)
            return {}

    @property
    def name(self) -> str | None:
        """Return the quota sensor name."""
        return "SePush API Quota"

    @property
    def native_value(self) -> StateType:
        """Return the API credits used so far today."""
        rate_limit = self._rate_limit()
        if not rate_limit:
            return self._attr_native_value
        count = int(rate_limit.get("used") or 0)
        self._attr_native_value = cast(StateType, count)
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not hasattr(self, "_attr_extra_state_attributes"):
            self._attr_extra_state_attributes = {}

        rate_limit = self._rate_limit()
        if not rate_limit:
            return self._attr_extra_state_attributes

        attrs = self._quota()
        attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        attrs = clean(attrs)

        self._attr_extra_state_attributes.update(attrs)
        return self._attr_extra_state_attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.native_value
        self.async_write_ha_state()


def stage_forecast_to_data(stage_forecast: list) -> list:
    """Convert stage forecast to serializable data."""
    data = []
    for forecast in stage_forecast:
        transformed_list = [
            {
                ATTR_STAGE: forecast.get(ATTR_STAGE).value,
                ATTR_START_TIME: schedule[0].isoformat(),
                ATTR_END_TIME: schedule[1].isoformat(),
            }
            for schedule in forecast.get(ATTR_SCHEDULE, [])
        ]
        data.extend(transformed_list)
    return data


def get_sensor_attrs(
    forecast: list,
    stage: Stage = Stage.NO_LOAD_SHEDDING,
    *,
    merge_contiguous: bool = False,
) -> dict:
    """Get sensor attributes for the given forecast and stage.

    ``merge_contiguous`` extends end times across back-to-back slots. It must be
    True only for the area forecast (#54); the stage ``planned`` list is
    contiguous by construction and must keep its per-stage boundaries and
    ``next_*`` fields (default False).
    """
    return build_sensor_attrs(
        forecast,
        stage,
        DEFAULT_DATA,
        datetime.now(UTC),
        merge_contiguous=merge_contiguous,
    )


def clean(data: dict) -> dict:
    """Remove default values from dict."""
    for key, value in CLEAN_DATA.items():
        if key not in data:
            continue
        if data[key] == value:
            del data[key]

    return data
