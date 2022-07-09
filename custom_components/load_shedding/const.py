"""Constants for LoadShedding integration."""
from __future__ import annotations

from typing import Final

from load_shedding import Stage

API: Final = "API"
ATTRIBUTION: Final = "Data provided by {provider}"
# TODO: Make Default stage configurable in config flow.
DEFAULT_STAGE = Stage.STAGE_4
DOMAIN: Final = "load_shedding"
MAX_FORECAST_DAYS: Final = 7
NAME: Final = "Load Shedding"
MANUFACTURER: Final = "@wernerhp"
DEFAULT_SCAN_INTERVAL = 61  # seconds

CONF_MUNICIPALITY: Final = "municipality"
CONF_OPTIONS: Final = "options"
CONF_PROVIDER: Final = "provider"
CONF_PROVINCE: Final = "province"
CONF_PROVINCE_ID: Final = "province_id"
CONF_SCHEDULE: Final = "schedule"
CONF_SCHEDULES: Final = "schedules"
CONF_AREA: Final = "area"
CONF_AREAS: Final = "areas"
CONF_AREA_ID: Final = "area_id"
CONF_SEARCH: Final = "search"
CONF_STAGE: Final = "stage"

ATTR_END_IN: Final = "ends_in"
ATTR_END_TIME: Final = "end_time"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_SCHEDULE: Final = "schedule"
ATTR_SCHEDULES: Final = "schedules"
ATTR_SCHEDULE_STAGE: Final = "schedule_stage"
ATTR_STAGE: Final = "stage"
ATTR_START_IN: Final = "starts_in"
ATTR_START_TIME: Final = "start_time"
ATTR_TIME_UNTIL: Final = "time_until"
