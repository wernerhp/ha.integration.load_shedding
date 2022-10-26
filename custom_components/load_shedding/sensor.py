"""Support for the LoadShedding service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_VIA_DEVICE,
    CONF_API_KEY,
    CONF_DESCRIPTION,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from load_shedding import Provider, Stage
from load_shedding.libs.sepush import SePush, SePushError
from load_shedding.providers import Area, Province, Stage, to_utc

from .const import (
    API,
    API_UPDATE_INTERVAL,
    ATTR_AREAS,
    ATTR_END_IN,
    ATTR_END_TIME,
    ATTR_FORECAST,
    ATTR_LAST_UPDATE,
    ATTR_NEXT_END_TIME,
    ATTR_NEXT_STAGE,
    ATTR_NEXT_START_TIME,
    ATTR_QUOTA,
    ATTR_SCHEDULE,
    ATTR_STAGE,
    ATTR_STAGE_FORECAST,
    ATTR_START_IN,
    ATTR_START_TIME,
    ATTRIBUTION,
    CONF_AREA,
    CONF_AREA_ID,
    CONF_AREAS,
    CONF_MUNICIPALITY,
    CONF_PROVINCE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MAX_FORECAST_DAYS,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

DEFAULT_DATA = {
    ATTR_STAGE: 0,
    ATTR_START_TIME: 0,
    ATTR_END_TIME: 0,
    ATTR_END_IN: 0,
    ATTR_START_IN: 0,
    ATTR_NEXT_STAGE: Stage.NO_LOAD_SHEDDING.value,
    ATTR_NEXT_START_TIME: 0,
    ATTR_NEXT_END_TIME: 0,
    ATTR_FORECAST: [],
    ATTR_SCHEDULE: [],
    ATTR_LAST_UPDATE: None,
    ATTR_ATTRIBUTION: ATTRIBUTION.format(provider="sepush.co.za"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add LoadShedding entities from a config_entry."""
    sepush = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    coordinator = LoadSheddingCoordinator(hass, sepush)
    coordinator.update_interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    for data in entry.data.get(CONF_AREAS, []):
        area = Area(
            id=data.get(CONF_AREA_ID),
            name=data.get(CONF_AREA),
            municipality=data.get(CONF_MUNICIPALITY),
            province=Province(data.get(CONF_PROVINCE_ID)),
        )
        coordinator.add_area(area)

    # async def _schedule_updates(*_):
    #     """Activate the data update coordinators."""
    #     coordinator.update_interval = timedelta(
    #         seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    #     )
    #     await coordinator.async_refresh()

    # if hass.state == CoreState.running:
    #     await _schedule_updates()
    # else:
    #     hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_updates)
    await coordinator.async_config_entry_first_refresh()

    entities: list[Entity] = []

    # async_add_entities(
    #     LoadSheddingStageSensorEntity(coordinator, idx) for idx, ent in enumerate(coordinator.data.get(ATTR_STAGE))
    # )

    for idx in coordinator.data.get(ATTR_STAGE):
        stage_entity = LoadSheddingStageSensorEntity(coordinator, idx)
        entities.append(stage_entity)

    for conf in entry.data.get(CONF_AREAS, {}):
        area = Area(
            id=conf.get(CONF_AREA_ID),
            name=conf.get(CONF_AREA),
            municipality=conf.get(CONF_MUNICIPALITY),
            province=Province(conf.get(CONF_PROVINCE_ID)),
        )
        area_entity = LoadSheddingScheduleSensorEntity(coordinator, area)
        entities.append(area_entity)

    quota_entity = LoadSheddingQuotaSensorEntity(coordinator)
    entities.append(quota_entity)

    async_add_entities(entities)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload Load Shedding Entry from config_entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    return unload_ok


class LoadSheddingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching LoadShedding stage from Provider."""

    def __init__(self, hass: HomeAssistant, sepush: SePush) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}",
            # update_method=self.async_update,
        )
        self.data = {}
        self.sepush = sepush
        self.areas: list[Area] = []
        self.last_update: datetime = None

    def add_area(self, area: Area = None) -> None:
        """Add a area to update."""
        self.areas.append(area)

    async def _async_update_data(self) -> dict:
        """Retrieve latest load shedding data."""

        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        diff = 0
        if self.last_update is not None:
            diff = (now - self.last_update).seconds

        _LOGGER.debug("Now: %s, Last Update: %s, Diff: %s", now, self.last_update, diff)
        if 0 < diff < API_UPDATE_INTERVAL:
            next_update = self.last_update + timedelta(seconds=API_UPDATE_INTERVAL)
            _LOGGER.debug(
                "Last update @ %s, Next update @ %s", self.last_update, next_update
            )
            return self.data

        try:
            data = await self.async_update_stage()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get stage: %s", err, exc_info=True)
            self.data[ATTR_STAGE] = {}
        else:
            self.data[ATTR_STAGE] = data
            self.last_update = now

        try:
            data = await self.async_update_schedule()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get schedule: %s", err, exc_info=True)
            self.data[ATTR_SCHEDULE] = []
        else:
            self.data[ATTR_SCHEDULE] = data
            self.last_update = now

        try:
            data = await self.async_update_quota()
        except UpdateFailed as err:
            _LOGGER.error("Unable to get quota: %s", err, exc_info=True)
            self.data[ATTR_QUOTA] = {}
        else:
            self.data[ATTR_QUOTA] = data
            self.last_update = now

        return self.data

    async def async_update_stage(self) -> dict:
        """Retrieve latest stage."""
        try:
            data = await self.hass.async_add_executor_job(self.sepush.status)
        except (SePushError) as err:
            raise UpdateFailed(err) from err
        else:
            area_forecast = {}
            statuses = data.get("status", {})
            for idx, area in statuses.items():
                forecast = [
                    {
                        ATTR_STAGE: Stage(int(area.get("stage", "0"))),
                        ATTR_START_TIME: datetime.fromisoformat(
                            area.get("stage_updated")
                        ).astimezone(timezone.utc),
                    }
                ]

                next_stages = area.get("next_stages", [])
                for i, next_stage in enumerate(next_stages):
                    # Prev
                    prev_end = datetime.fromisoformat(
                        next_stage.get("stage_start_timestamp")
                    )
                    forecast[i][ATTR_END_TIME] = prev_end.astimezone(timezone.utc)

                    # Next
                    forecast.append(
                        {
                            ATTR_STAGE: Stage(int(next_stage.get("stage", "0"))),
                            ATTR_START_TIME: datetime.fromisoformat(
                                next_stage.get("stage_start_timestamp")
                            ).astimezone(timezone.utc),
                        }
                    )

                filtered = []
                for f in forecast:
                    if ATTR_END_TIME in f and f.get(ATTR_END_TIME) >= self.now:
                        filtered.append(f)

                area_forecast[idx] = {
                    ATTR_NAME: area.get("name", ""),
                    ATTR_FORECAST: filtered,
                }

        return area_forecast

    async def async_update_schedule(self) -> dict:
        """Retrieve schedule data."""
        areas_schedule_data: dict = {}

        for area in self.areas:
            # Get foreacast for area
            forecast = []
            try:
                data = await self.hass.async_add_executor_job(self.sepush.area, area.id)
            except (SePushError) as err:
                raise UpdateFailed(err) from err

            for event in data.get("events", {}):
                note = event.get("note")
                parts = str(note).split(" ")
                stage = Stage(int(parts[1]))
                start = datetime.fromisoformat(event.get("start")).astimezone(
                    timezone.utc
                )
                end = datetime.fromisoformat(event.get("end")).astimezone(timezone.utc)

                forecast.append(
                    {
                        ATTR_STAGE: stage,
                        ATTR_START_TIME: start,
                        ATTR_END_TIME: end,
                    }
                )

            # Get schedule for area
            stage_schedule = {}
            sast = timezone(timedelta(hours=+2), "SAST")
            for day in data.get("schedule", {}).get("days", []):
                date = datetime.strptime(day.get("date"), "%Y-%m-%d")
                stages = day.get("stages", [])
                for i, stage in enumerate(stages):
                    schedule = []
                    for slot in stages[i]:
                        start_str, end_str = slot.strip().split("-")
                        start = datetime.strptime(start_str, "%H:%M").replace(
                            year=date.year,
                            month=date.month,
                            day=date.day,
                            second=0,
                            microsecond=0,
                            tzinfo=sast,
                        )
                        end = datetime.strptime(end_str, "%H:%M").replace(
                            year=date.year,
                            month=date.month,
                            day=date.day,
                            second=0,
                            microsecond=0,
                            tzinfo=sast,
                        )
                        if end < start:
                            end = end + timedelta(days=1)
                        schedule.append((start, end))

                    schedule = to_utc(schedule)
                    stage_schedule[i + 1] = schedule

            areas_schedule_data[area.id] = {
                ATTR_FORECAST: forecast,
                ATTR_SCHEDULE: stage_schedule,
            }

        return areas_schedule_data

    async def async_update_quota(self) -> dict:
        """Retrieve latest quota."""
        try:
            data = await self.hass.async_add_executor_job(self.sepush.check_allowance)
        except (SePushError) as err:
            raise UpdateFailed(err) from err

        return data.get("allowance", {})


@dataclass
class LoadSheddingSensorDescription(SensorEntityDescription):
    """Class describing LoadShedding sensor entities."""


class LoadSheddingStageSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Stage entity."""

    def __init__(self, coordinator: CoordinatorEntity, idx: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.idx = idx

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} stage",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} stage",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        self._device_id = f"{NAME}"
        self._state: StateType = None
        self._attrs = {}
        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        name = self.data.get("name", "")
        self._attr_name = f"{NAME} {name} Stage"
        self._attr_unique_id = f"stage_{name}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        if self.data:
            stage = self.data.get(ATTR_FORECAST)[0].get(ATTR_STAGE, Stage.UNKNOWN)
            if stage in [Stage.UNKNOWN]:
                return self._state
            self._state = cast(StateType, stage)
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        if not self.data:
            return self._attrs

        # stage = self.data.get(ATTR_STAGE, Stage.UNKNOWN)
        # if stage in [Stage.UNKNOWN]:
        #     return self._attrs

        stage_forecast = self.data.get(ATTR_FORECAST, [])

        now = datetime.now(timezone.utc)
        data = get_sensor_attrs(stage_forecast, stage_forecast[0].get(ATTR_STAGE))
        data[ATTR_FORECAST] = []
        for f in stage_forecast:
            if ATTR_END_TIME in f and f.get(ATTR_END_TIME) < now:
                continue
            forecast = {
                ATTR_STAGE: f.get(ATTR_STAGE).value,
                ATTR_START_TIME: f.get(ATTR_START_TIME).isoformat(),
            }
            if ATTR_END_TIME in f:
                forecast[ATTR_END_TIME] = f.get(ATTR_END_TIME).isoformat()

            data[ATTR_FORECAST].append(forecast)

        self._attrs.update(clean(data))
        self._attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data.get(ATTR_STAGE, {}).get(self.idx)
        self.async_write_ha_state()


class LoadSheddingScheduleSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Schedule entity."""

    coordinator: CoordinatorEntity

    def __init__(self, coordinator: CoordinatorEntity, area: Area) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.data = self.coordinator.data.get(ATTR_SCHEDULE, [])
        self.area = area

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} schedule {area.id}",
            icon="mdi:calendar",
            name=f"{DOMAIN} schedule {area.name}",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        # self._device_id = "loadshedding.eskom.co.za"
        self._device_id = f"{NAME}"
        self._state: StateType = None
        self._attrs = {}
        self._attr_name = f"{NAME} {area.name}"
        self._attr_unique_id = f"{area.id}"

    @property
    def native_value(self) -> StateType:
        """Return the schedule state."""
        if not self.data:
            return self._state

        area = self.data.get(self.area.id)

        forecast = area.get(ATTR_FORECAST)
        self._state = cast(StateType, STATE_OFF)

        if not forecast:
            return self._state

        next = forecast[0]
        if next.get(ATTR_STAGE) == Stage.NO_LOAD_SHEDDING:
            return self._state

        now = datetime.now(timezone.utc)
        if next.get(ATTR_START_TIME) <= now <= next.get(ATTR_END_TIME):
            self._state = cast(StateType, STATE_ON)

        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.data:
            return self._attrs

        data = self._attrs

        data = []
        now = datetime.now(timezone.utc)
        # stage_schedule = self.data.get(self.area.id, []).get(ATTR_SCHEDULE)
        # for stage in stage_schedule:
        #     for s in stage_schedule[stage]:
        #         start_time = s[0]
        #         end_time = s[1]

        #         if start_time > now + timedelta(days=MAX_FORECAST_DAYS):
        #             continue

        #         if end_time < now:
        #             continue

        #         data.append(
        #             {
        #                 ATTR_STAGE: Stage(stage),
        #                 ATTR_START_TIME: start_time,
        #                 ATTR_END_TIME: end_time,
        #             }
        #         )

        # area_schedule = data

        # if area_schedule:
        #     data = get_sensor_attrs(area_schedule)
        #     data[ATTR_SCHEDULE] = []
        #     for s in area_schedule:
        #         data[ATTR_SCHEDULE].append(
        #             {
        #                 ATTR_STAGE: s.get(ATTR_STAGE).value,
        #                 ATTR_START_TIME: s.get(ATTR_START_TIME).isoformat(),
        #                 ATTR_END_TIME: s.get(ATTR_END_TIME).isoformat(),
        #             }
        #         )

        area_forecast = self.data.get(self.area.id, []).get(ATTR_FORECAST)
        if area_forecast:
            data = get_sensor_attrs(area_forecast)
            data[ATTR_FORECAST] = []
            for f in area_forecast:
                if ATTR_END_TIME in f and f.get(ATTR_END_TIME) < now:
                    continue
                data[ATTR_FORECAST].append(
                    {
                        ATTR_STAGE: f.get(ATTR_STAGE).value,
                        ATTR_START_TIME: f.get(ATTR_START_TIME).isoformat(),
                        ATTR_END_TIME: f.get(ATTR_END_TIME).isoformat(),
                    }
                )

        self._attrs.update(clean(data))
        self._attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data.get(ATTR_SCHEDULE, self.data)
        self.async_write_ha_state()


class LoadSheddingQuotaSensorEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Define a LoadShedding Quota entity."""

    def __init__(self, coordinator: CoordinatorEntity) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.data = self.coordinator.data.get(ATTR_QUOTA, {})

        description = LoadSheddingSensorDescription(
            key=f"{DOMAIN} SePush Quota",
            icon="mdi:lightning-bolt-outline",
            name=f"{DOMAIN} SePush Quota",
            entity_registry_enabled_default=True,
        )

        self.entity_description = description
        self._device_id = f"{NAME}"
        self._state: StateType = None
        self._attrs = {}
        self._attr_name = f"{NAME} SePush Quota"
        self._attr_unique_id = f"se_push_quota"

    @property
    def native_value(self) -> StateType:
        """Return the stage state."""
        if self.data:
            count = int(self.data.get("count", 0))
            self._state = cast(StateType, count)
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this LoadShedding receiver."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._device_id)},
            ATTR_NAME: f"{NAME}",
            ATTR_MANUFACTURER: MANUFACTURER,
            ATTR_MODEL: API,
            ATTR_VIA_DEVICE: (DOMAIN, self._device_id),
        }

    @property
    def extra_state_attributes(self) -> dict[str, list, Any]:
        """Return the state attributes."""
        if not self.data:
            return self._attrs

        self._attrs.update(self.data)
        self._attrs[ATTR_LAST_UPDATE] = self.coordinator.last_update
        return self._attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.data = self.coordinator.data.get(ATTR_QUOTA, {})
        self.async_write_ha_state()


def stage_forecast_to_data(stage_forecast: list) -> list:
    """Convert stage forecast to serializable data"""
    data = []
    for forecast in stage_forecast:
        for schedule in forecast.get(ATTR_SCHEDULE, []):
            data.append(
                {
                    ATTR_STAGE: forecast.get(ATTR_STAGE).value,
                    ATTR_START_TIME: schedule[0].isoformat(),
                    ATTR_END_TIME: schedule[1].isoformat(),
                }
            )
    return data


def get_sensor_attrs(forecast: list, stage: Stage = Stage.NO_LOAD_SHEDDING) -> dict:
    """Get sensor attributes for the given forecast and stage"""
    if not forecast:
        return {
            ATTR_STAGE: stage.value,
        }

    now = datetime.now(timezone.utc)
    data = dict(DEFAULT_DATA)
    data[ATTR_STAGE] = stage.value

    current, next = {}, {}
    if now < forecast[0].get(ATTR_START_TIME):
        # before
        next = forecast[0]
    elif forecast[0].get(ATTR_START_TIME) <= now <= forecast[0].get(ATTR_END_TIME, now):
        # during
        current = forecast[0]
        if len(forecast) > 1:
            next = forecast[1]
    elif forecast[0].get(ATTR_END_TIME) < now:
        # after
        if len(forecast) > 1:
            next = forecast[1]

    if current:
        data[ATTR_STAGE] = current.get(ATTR_STAGE).value
        data[ATTR_START_TIME] = current.get(ATTR_START_TIME).isoformat()
        if ATTR_END_TIME in current:
            data[ATTR_END_TIME] = current.get(ATTR_END_TIME).isoformat()

            end_time = current.get(ATTR_END_TIME)
            ends_in = end_time - now
            ends_in = ends_in - timedelta(microseconds=ends_in.microseconds)
            ends_in = int(ends_in.total_seconds() / 60)  # minutes
            data[ATTR_END_IN] = ends_in

    if next:
        data[ATTR_NEXT_STAGE] = next.get(ATTR_STAGE).value
        data[ATTR_NEXT_START_TIME] = next.get(ATTR_START_TIME).isoformat()
        if ATTR_END_TIME in next:
            data[ATTR_NEXT_END_TIME] = next.get(ATTR_END_TIME).isoformat()

        start_time = next.get(ATTR_START_TIME)
        starts_in = start_time - now
        starts_in = starts_in - timedelta(microseconds=starts_in.microseconds)
        starts_in = int(starts_in.total_seconds() / 60)  # minutes
        data[ATTR_START_IN] = starts_in

    return data


def clean(data: dict) -> dict:
    """Remove default values from dict"""
    for (key, value) in DEFAULT_DATA.items():
        if data[key] == value:
            del data[key]

    return data
