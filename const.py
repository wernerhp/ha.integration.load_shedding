"""Constants for LoadShedding integration."""
from __future__ import annotations

from typing import Final

from load_shedding.providers import eskom

API_IMPERIAL: Final = "Imperial"
API_METRIC: Final = "Metric"
ATTRIBUTION: Final = "Data provided by Eskom"
DOMAIN: Final = "load_shedding"
MANUFACTURER: Final = "Eskom"
MAX_FORECAST_DAYS: Final = 4
NAME: Final = "Load Shedding"
CONF_SCHEDULE: Final = "schedule"

ATTR_SCHEDULE: Final = "schedule"
ATTR_STAGE: Final = "state"
CONF_MUNICIPALITY = "municipality"
CONF_OPTIONS = "options"
CONF_PROVINCE = "province"
CONF_PROVINCE_ID = "province_id"
CONF_PROVIDER = "provider"
CONF_SUBURB = "suburb"
CONF_SUBURBS = "suburbs"
CONF_SUBURB_ID = "suburb_id"
ATTR_NEXT_START = "next_start"
ATTR_NEXT_END = "next_end"
ATTR_SUBURBS = "suburbs"
ATTR_LAST_UPDATE = "last_update"
ATTR_TIME_UNTIL = "time_until"

PROVIDER = eskom.Eskom

DEFAULT_SCAN_INTERVAL = 1800  # seconds
