"""Constants for LoadShedding integration."""
from __future__ import annotations

from typing import Final

from load_shedding.providers import eskom

ATTRIBUTION: Final = "Data provided by Eskom"
DEFAULT_SCAN_INTERVAL = 60  # seconds
DOMAIN: Final = "load_shedding"
MANUFACTURER: Final = "Eskom"
MAX_FORECAST_DAYS: Final = 7
NAME: Final = "Load Shedding"
PROVIDER = eskom.Eskom

CONF_MUNICIPALITY: Final = "municipality"
CONF_OPTIONS: Final = "options"
CONF_PROVIDER: Final = "provider"
CONF_PROVINCE: Final = "province"
CONF_PROVINCE_ID: Final = "province_id"
CONF_SCHEDULE: Final = "schedule"
CONF_SUBURB: Final = "suburb"
CONF_SUBURBS: Final = "suburbs"
CONF_SUBURB_ID: Final = "suburb_id"

ATTR_LAST_UPDATE: Final = "last_update"
ATTR_NEXT_END: Final = "next_end"
ATTR_NEXT_START: Final = "next_start"
ATTR_SCHEDULE: Final = "schedule"
ATTR_STAGE: Final = "state"
ATTR_SUBURBS:  Final = "suburbs"
ATTR_TIME_UNTIL: Final = "time_until"
