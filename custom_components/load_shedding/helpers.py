"""Pure, Home Assistant-independent helpers for the Load Shedding integration.

Everything in this module is free of ``homeassistant`` imports so it can be
unit-tested without a full Home Assistant install. The entity/coordinator
modules import these functions and supply the HA-specific glue (entity classes,
``CalendarEvent`` objects, ``STATE_ON``/``STATE_OFF`` mapping, etc.).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from load_shedding.providers import Stage

try:  # Home Assistant runtime (imported as a package submodule)
    from .const import (
        ATTR_END_IN,
        ATTR_END_TIME,
        ATTR_FORECAST,
        ATTR_NEXT_END_TIME,
        ATTR_NEXT_STAGE,
        ATTR_NEXT_START_TIME,
        ATTR_STAGE,
        ATTR_START_IN,
        ATTR_START_TIME,
    )
except ImportError:  # standalone/test import (component dir on sys.path)
    from const import (  # type: ignore[no-redef]
        ATTR_END_IN,
        ATTR_END_TIME,
        ATTR_FORECAST,
        ATTR_NEXT_END_TIME,
        ATTR_NEXT_STAGE,
        ATTR_NEXT_START_TIME,
        ATTR_STAGE,
        ATTR_START_IN,
        ATTR_START_TIME,
    )


def should_refresh(
    last_update: datetime | None, now: datetime, interval: int
) -> bool:
    """Return True when a coordinator should fetch fresh data.

    Uses ``timedelta.total_seconds()`` (not ``.seconds``) so the day component
    is not discarded — the bug behind the area schedule freezing once
    ``last_update`` was more than ~24h old (#61/#71).
    """
    if last_update is None:
        return True
    diff = (now - last_update).total_seconds()
    # Within the throttle window -> skip. Otherwise (including diff == 0 or
    # diff >= interval) refresh.
    return not (0 < diff < interval)


def continuous_block_end(forecast: list, start_index: int) -> tuple[datetime, int]:
    """Return ``(end_time, next_index)`` for a continuous outage block.

    Walks forward across back-to-back slots (one slot's end equals the next
    slot's start) so the end reflects the true continuous outage even when the
    stage changes mid-block. ``next_index`` is the first slot not in the block.
    """
    end_time = forecast[start_index].get(ATTR_END_TIME)
    index = start_index + 1
    while index < len(forecast) and forecast[index].get(ATTR_START_TIME) == end_time:
        end_time = forecast[index].get(ATTR_END_TIME)
        index += 1
    return end_time, index


def merge_forecast(forecast: list) -> list:
    """Merge back-to-back forecast slots into calendar-style blocks.

    Contiguous slots are combined into one entry; when the stage changes across
    the block the stage labels are joined (e.g. "Stage 2/Stage 4").
    """
    merged: list = []
    for slot in forecast:
        start = slot.get(ATTR_START_TIME)
        end = slot.get(ATTR_END_TIME)
        stage = str(slot.get(ATTR_STAGE))

        if merged and merged[-1][ATTR_END_TIME] == start:
            prev = merged[-1]
            prev[ATTR_END_TIME] = end
            if stage not in prev[ATTR_STAGE].split("/"):
                prev[ATTR_STAGE] = f"{prev[ATTR_STAGE]}/{stage}"
        else:
            merged.append(
                {
                    ATTR_STAGE: stage,
                    ATTR_START_TIME: start,
                    ATTR_END_TIME: end,
                }
            )

    return merged


def is_load_shedding_active(forecast: list, now: datetime) -> bool:
    """Return True if a forecast event is active at ``now``.

    Defaults to inactive and only reports active for a currently-running,
    non-NO_LOAD_SHEDDING event. Guarantees the state clears when load shedding
    ends, even when every forecast event is already in the past (#103/#104).
    """
    for event in forecast:
        end_time = event.get(ATTR_END_TIME)
        start_time = event.get(ATTR_START_TIME)

        if end_time is not None and end_time < now:
            continue

        return bool(
            event.get(ATTR_STAGE) != Stage.NO_LOAD_SHEDDING
            and start_time is not None
            and end_time is not None
            and start_time <= now <= end_time
        )
    return False


def _minutes(delta: timedelta) -> int:
    """Whole minutes in a timedelta, truncating sub-second precision."""
    delta = delta - timedelta(microseconds=delta.microseconds)
    return int(delta.total_seconds() / 60)


def summarize_forecast(
    forecast: list, now: datetime, *, merge_contiguous: bool
) -> dict:
    """Compute current/next outage summary fields from a forecast list.

    Returns a dict with any of: stage, start_time, end_time, ends_in,
    next_stage, next_start_time, next_end_time, starts_in. Times are returned as
    ``datetime`` objects (callers isoformat them as needed).

    ``merge_contiguous`` controls whether back-to-back slots are treated as one
    continuous outage. This must be True for the *area forecast* (where
    contiguous slots are one outage spanning a stage change, #54) but False for
    the *stage planned* list (where contiguous entries are distinct stage
    transitions whose individual boundaries and ``next_*`` must be preserved).
    """
    result: dict = {}
    if not forecast:
        return result

    cur: dict = {}
    nxt: dict = {}
    nxt_index: int | None = None

    if now < forecast[0].get(ATTR_START_TIME):
        # before
        nxt, nxt_index = forecast[0], 0
    elif forecast[0].get(ATTR_START_TIME) <= now <= forecast[0].get(ATTR_END_TIME, now):
        # during
        cur = forecast[0]
        if merge_contiguous:
            _, next_index = continuous_block_end(forecast, 0)
        else:
            next_index = 1
        if next_index < len(forecast):
            nxt, nxt_index = forecast[next_index], next_index
    elif forecast[0].get(ATTR_END_TIME) < now:
        # after
        if len(forecast) > 1:
            nxt, nxt_index = forecast[1], 1

    if cur:
        try:
            result[ATTR_STAGE] = cur.get(ATTR_STAGE).value
        except AttributeError:
            result[ATTR_STAGE] = Stage.NO_LOAD_SHEDDING.value
        result[ATTR_START_TIME] = cur.get(ATTR_START_TIME)

        if merge_contiguous:
            end_time, _ = continuous_block_end(forecast, 0)
        else:
            end_time = cur.get(ATTR_END_TIME)
        if end_time is not None:
            result[ATTR_END_TIME] = end_time
            result[ATTR_END_IN] = _minutes(end_time - now)

    if nxt:
        try:
            result[ATTR_NEXT_STAGE] = nxt.get(ATTR_STAGE).value
        except AttributeError:
            result[ATTR_NEXT_STAGE] = Stage.NO_LOAD_SHEDDING.value
        result[ATTR_NEXT_START_TIME] = nxt.get(ATTR_START_TIME)

        if merge_contiguous and nxt_index is not None:
            next_end_time, _ = continuous_block_end(forecast, nxt_index)
        else:
            next_end_time = nxt.get(ATTR_END_TIME)
        if next_end_time is not None:
            result[ATTR_NEXT_END_TIME] = next_end_time

        result[ATTR_START_IN] = _minutes(nxt.get(ATTR_START_TIME) - now)

    return result


def build_sensor_attrs(
    forecast: list,
    stage: Stage,
    default_data: dict,
    now: datetime,
    *,
    merge_contiguous: bool,
) -> dict:
    """Build the full, HA-serialisable sensor attribute dict.

    ``merge_contiguous`` must be True for the *area forecast* (contiguous slots
    are one continuous outage, #54) and False for the *stage planned* list
    (contiguous entries are distinct stage transitions whose individual
    boundaries and ``next_*`` fields must be preserved — review HIGH finding).
    """
    if not forecast:
        return {ATTR_STAGE: stage.value}

    data = dict(default_data)
    data[ATTR_STAGE] = stage.value

    summary = summarize_forecast(forecast, now, merge_contiguous=merge_contiguous)
    for key, value in summary.items():
        data[key] = value.isoformat() if isinstance(value, datetime) else value

    return data


def filter_restorable_attrs(attributes: dict, allowed) -> dict:
    """Return only the data-bearing attributes worth restoring after a restart.

    Reserved/entity-managed attributes (friendly_name, icon, unit, ...) are
    excluded by passing an explicit ``allowed`` whitelist (#31).
    """
    if not attributes:
        return {}
    allowed = set(allowed)
    return {key: value for key, value in attributes.items() if key in allowed}


def build_calendar_events(area_forecasts: list, multi_stage_events: bool) -> list:
    """Build the ordered list of forecast calendar events as plain dicts.

    ``area_forecasts`` is a list of ``{"id", "name", "forecast"}`` dicts. Each
    returned event is ``{"start", "end", "summary", "location"}``. Callers wrap
    these into HA ``CalendarEvent`` objects.

    When ``multi_stage_events`` is set, contiguous events are merged **per
    location** so that adjacent slots from different areas are never combined
    into one event (review M1).
    """
    events: list = []
    for area in area_forecasts:
        forecast = area.get(ATTR_FORECAST)
        if not forecast:
            continue
        for slot in forecast:
            events.append(
                {
                    "start": slot.get(ATTR_START_TIME),
                    "end": slot.get(ATTR_END_TIME),
                    "summary": str(slot.get(ATTR_STAGE)),
                    "location": area.get("name"),
                }
            )

    events.sort(key=lambda event: event["start"])

    if multi_stage_events:
        # Merge contiguous slots, but only within the same location.
        by_location: dict = {}
        order: list = []
        for event in events:
            location = event["location"]
            if location not in by_location:
                by_location[location] = []
                order.append(location)
            group = by_location[location]
            if group and group[-1]["end"] == event["start"]:
                group[-1]["summary"] = f"{group[-1]['summary']}/{event['summary']}"
                group[-1]["end"] = event["end"]
            else:
                group.append(event)
        events = [event for location in order for event in by_location[location]]
        events.sort(key=lambda event: event["start"])

    return events


def current_event(events: list, now: datetime) -> dict | None:
    """Return the first event that has not yet ended, or None."""
    for event in events:
        if event["end"] > now:
            return event
    return None


def events_in_range(events: list, start_date: datetime, end_date: datetime) -> list:
    """Return events overlapping the ``[start_date, end_date)`` window."""
    result: list = []
    for event in events:
        if event["end"] <= start_date:
            continue
        if event["start"] >= end_date:
            continue
        result.append(event)
    return result
