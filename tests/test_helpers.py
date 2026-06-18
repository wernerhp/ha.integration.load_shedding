"""Unit tests for the dependency-free helpers.

These exercise the pure logic extracted from the entity/coordinator modules so
the integration's behaviour can be verified without a full Home Assistant
install. ``conftest.py`` puts the component directory on ``sys.path``.
"""
from datetime import datetime, timedelta, timezone

import helpers
from load_shedding.providers import Stage

UTC = timezone.utc
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)

ATTR_STAGE = "stage"
ATTR_START_TIME = "start_time"
ATTR_END_TIME = "end_time"
ATTR_FORECAST = "forecast"


def _slot(stage, start_min, end_min):
    """Build a forecast slot using minute offsets from NOW."""
    return {
        ATTR_STAGE: Stage(stage) if isinstance(stage, int) else stage,
        ATTR_START_TIME: NOW + timedelta(minutes=start_min),
        ATTR_END_TIME: NOW + timedelta(minutes=end_min),
    }


# ---------------------------------------------------------------------------
# should_refresh — locks #61/#71 (.total_seconds() vs .seconds)
# ---------------------------------------------------------------------------

class TestShouldRefresh:
    def test_none_last_update_refreshes(self):
        assert helpers.should_refresh(None, NOW, 86400) is True

    def test_within_interval_skips(self):
        assert helpers.should_refresh(NOW - timedelta(hours=1), NOW, 86400) is False

    def test_more_than_a_day_old_refreshes(self):
        # The .seconds bug returned a small number here and wrongly skipped.
        assert helpers.should_refresh(
            NOW - timedelta(days=2, minutes=5), NOW, 86400
        ) is True

    def test_exactly_interval_refreshes(self):
        assert helpers.should_refresh(
            NOW - timedelta(seconds=86400), NOW, 86400
        ) is True

    def test_just_under_interval_skips(self):
        assert helpers.should_refresh(
            NOW - timedelta(seconds=86399), NOW, 86400
        ) is False


# ---------------------------------------------------------------------------
# continuous_block_end
# ---------------------------------------------------------------------------

class TestContinuousBlockEnd:
    def test_single_slot(self):
        f = [_slot(2, 0, 120)]
        end, nxt = helpers.continuous_block_end(f, 0)
        assert end == f[0][ATTR_END_TIME]
        assert nxt == 1

    def test_contiguous_run(self):
        f = [_slot(2, 0, 120), _slot(4, 120, 360), _slot(4, 360, 480)]
        end, nxt = helpers.continuous_block_end(f, 0)
        assert end == NOW + timedelta(minutes=480)
        assert nxt == 3

    def test_gap_stops_walk(self):
        f = [_slot(2, 0, 120), _slot(4, 200, 360)]
        end, nxt = helpers.continuous_block_end(f, 0)
        assert end == NOW + timedelta(minutes=120)
        assert nxt == 1


# ---------------------------------------------------------------------------
# merge_forecast
# ---------------------------------------------------------------------------

class TestMergeForecast:
    def test_empty(self):
        assert helpers.merge_forecast([]) == []

    def test_contiguous_merge_joins_labels(self):
        f = [_slot(2, 0, 120), _slot(4, 120, 360), _slot(4, 360, 480)]
        merged = helpers.merge_forecast(f)
        assert len(merged) == 1
        assert merged[0][ATTR_STAGE] == "Stage 2/Stage 4"
        assert merged[0][ATTR_START_TIME] == NOW
        assert merged[0][ATTR_END_TIME] == NOW + timedelta(minutes=480)

    def test_gap_keeps_separate(self):
        f = [_slot(2, 0, 120), _slot(2, 600, 720)]
        merged = helpers.merge_forecast(f)
        assert len(merged) == 2


# ---------------------------------------------------------------------------
# is_load_shedding_active — locks #103/#104
# ---------------------------------------------------------------------------

class TestIsLoadSheddingActive:
    def test_empty(self):
        assert helpers.is_load_shedding_active([], NOW) is False

    def test_all_past(self):
        assert helpers.is_load_shedding_active([_slot(2, -180, -60)], NOW) is False

    def test_ongoing(self):
        assert helpers.is_load_shedding_active([_slot(2, -10, 50)], NOW) is True

    def test_future_only(self):
        assert helpers.is_load_shedding_active([_slot(2, 120, 240)], NOW) is False

    def test_past_then_ongoing(self):
        f = [_slot(2, -180, -60), _slot(4, -10, 50)]
        assert helpers.is_load_shedding_active(f, NOW) is True

    def test_no_load_shedding_stage(self):
        f = [_slot(Stage.NO_LOAD_SHEDDING, -10, 50)]
        assert helpers.is_load_shedding_active(f, NOW) is False


# ---------------------------------------------------------------------------
# summarize_forecast
# ---------------------------------------------------------------------------

class TestSummarizeForecast:
    def test_empty(self):
        assert helpers.summarize_forecast([], NOW, merge_contiguous=True) == {}

    def test_area_merges_back_to_back(self):
        # During s0; s1 is contiguous (stage change); s2 separate.
        f = [_slot(2, -30, 90), _slot(4, 90, 330), _slot(2, 600, 720)]
        out = helpers.summarize_forecast(f, NOW, merge_contiguous=True)
        assert out[ATTR_END_TIME] == NOW + timedelta(minutes=330)
        assert out["ends_in"] == 330
        assert out["next_start_time"] == NOW + timedelta(minutes=600)
        assert out["next_stage"] == 2

    def test_before_first_event(self):
        f = [_slot(2, 60, 180)]
        out = helpers.summarize_forecast(f, NOW, merge_contiguous=True)
        assert ATTR_END_TIME not in out  # no current event
        assert out["next_start_time"] == NOW + timedelta(minutes=60)
        assert out["starts_in"] == 60


# ---------------------------------------------------------------------------
# filter_restorable_attrs — locks #31 whitelist
# ---------------------------------------------------------------------------

class TestFilterRestorableAttrs:
    ALLOWED = ("forecast", "forecast_calendar", "stage", "area_id")

    def test_empty(self):
        assert helpers.filter_restorable_attrs({}, self.ALLOWED) == {}

    def test_filters_reserved(self):
        attributes = {
            "friendly_name": "Milnerton",
            "icon": "mdi:calendar",
            "attribution": "x",
            "forecast": [{"stage": "Stage 2"}],
            "stage": 2,
            "area_id": "abc",
        }
        out = helpers.filter_restorable_attrs(attributes, self.ALLOWED)
        assert set(out) == {"forecast", "stage", "area_id"}


# ---------------------------------------------------------------------------
# calendar event helpers
# ---------------------------------------------------------------------------

class TestCalendarHelpers:
    def _area(self, name, slots):
        return {"id": name, "name": name, ATTR_FORECAST: slots}

    def test_build_sorts_by_start(self):
        areas = [self._area("A", [_slot(4, 120, 240), _slot(2, 0, 60)])]
        events = helpers.build_calendar_events(areas, multi_stage_events=False)
        assert [e["start"] for e in events] == [
            NOW, NOW + timedelta(minutes=120)
        ]

    def test_single_area_multi_stage_merge(self):
        areas = [self._area("A", [_slot(2, 0, 120), _slot(4, 120, 360)])]
        events = helpers.build_calendar_events(areas, multi_stage_events=True)
        assert len(events) == 1
        assert events[0]["summary"] == "Stage 2/Stage 4"

    def test_empty_area_skipped(self):
        areas = [self._area("A", None), self._area("B", [])]
        assert helpers.build_calendar_events(areas, multi_stage_events=False) == []

    def test_current_event_picks_first_not_ended(self):
        events = helpers.build_calendar_events(
            [self._area("A", [_slot(2, -180, -60), _slot(4, -10, 50)])],
            multi_stage_events=False,
        )
        cur = helpers.current_event(events, NOW)
        assert cur is not None
        assert cur["end"] == NOW + timedelta(minutes=50)

    def test_current_event_none_when_all_past(self):
        events = helpers.build_calendar_events(
            [self._area("A", [_slot(2, -180, -60)])], multi_stage_events=False
        )
        assert helpers.current_event(events, NOW) is None

# ---------------------------------------------------------------------------
# build_sensor_attrs — locks review HIGH (stage vs area merge distinction)
# ---------------------------------------------------------------------------

class TestBuildSensorAttrs:
    DEFAULT = {ATTR_STAGE: 0, "ends_in": 0, "next_stage": 0}

    def test_empty_returns_stage_only(self):
        out = helpers.build_sensor_attrs(
            [], Stage.NO_LOAD_SHEDDING, self.DEFAULT, NOW, merge_contiguous=False
        )
        assert out == {ATTR_STAGE: Stage.NO_LOAD_SHEDDING.value}

    def test_area_merges_contiguous(self):
        # Area forecast: contiguous stage change is one continuous outage (#54).
        forecast = [_slot(2, -30, 90), _slot(4, 90, 330)]
        out = helpers.build_sensor_attrs(
            forecast, Stage(2), self.DEFAULT, NOW, merge_contiguous=True
        )
        assert out["ends_in"] == 330
        assert out[ATTR_END_TIME] == (NOW + timedelta(minutes=330)).isoformat()

    def test_stage_planned_not_merged_preserves_next(self):
        # Stage planned list is contiguous by construction; transitions must be
        # preserved with merge_contiguous=False (review HIGH regression lock).
        planned = [_slot(2, -60, 120), _slot(4, 120, 360), _slot(6, 360, 360 + 7 * 24 * 60)]
        out = helpers.build_sensor_attrs(
            planned, Stage(2), self.DEFAULT, NOW, merge_contiguous=False
        )
        assert out["ends_in"] == 120  # current stage ends in 2h, not in 7 days
        assert out["next_stage"] == 4
        assert out["next_start_time"] == (NOW + timedelta(minutes=120)).isoformat()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))



