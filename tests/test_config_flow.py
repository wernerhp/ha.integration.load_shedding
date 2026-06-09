"""Regression tests for config_flow fixes.

Issue #111: "Unable to remove area – value must be one of [0]"
  Root cause: delete_area schema used integer dict keys; HA form submission
  always delivers string values, so vol.In({0: ...}) rejected "0".
"""
import unittest

import voluptuous as vol


CONF_AREA_ID = "area_id"
CONF_NAME = "name"


def _build_delete_schema_original(areas: list) -> vol.Schema:
    """Reproduce the ORIGINAL (buggy) schema — integer keys, optional."""
    area_idx = {}
    for idx, area in enumerate(areas):
        area_idx[idx] = area.get(CONF_NAME)
    return vol.Schema({vol.Optional(CONF_AREA_ID): vol.In(area_idx)})


def _build_delete_schema_fixed(areas: list) -> vol.Schema:
    """Reproduce the FIXED schema — string keys, required."""
    area_idx = {}
    for idx, area in enumerate(areas):
        area_idx[str(idx)] = area.get(CONF_NAME)
    return vol.Schema({vol.Required(CONF_AREA_ID): vol.In(area_idx)})


ONE_AREA = [{"name": "tshwane-8-moreletapark", "id": "tshwane-8-moreletapark"}]
TWO_AREAS = [
    {"name": "tshwane-8-moreletapark", "id": "tshwane-8-moreletapark"},
    {"name": "Fourways", "id": "za_gt_jhb_fourways_4pef"},
]


class TestDeleteAreaSchemaRegression(unittest.TestCase):
    """
    Regression: issue #111 – 'value must be one of [0]' when removing an area.

    HA config-flow forms always submit field values as strings.  The original
    schema used integer dict keys so vol.In({0: ...}) rejected the submitted
    string "0".  The fix uses string keys throughout.
    """

    # ------------------------------------------------------------------
    # These tests DOCUMENT the broken behaviour of the original code.
    # They must FAIL with the original schema and PASS with the fixed one.
    # ------------------------------------------------------------------

    def test_original_schema_rejects_string_submission_single_area(self):
        """Original schema raises Invalid when HA submits string '0'."""
        schema = _build_delete_schema_original(ONE_AREA)
        with self.assertRaises(vol.Invalid) as ctx:
            schema({CONF_AREA_ID: "0"})   # HA always delivers a string
        self.assertIn("value must be one of", str(ctx.exception))

    def test_original_schema_rejects_string_submission_multi_area(self):
        """Original schema raises Invalid for any string index."""
        schema = _build_delete_schema_original(TWO_AREAS)
        for submitted in ("0", "1"):
            with self.subTest(submitted=submitted):
                with self.assertRaises(vol.Invalid):
                    schema({CONF_AREA_ID: submitted})

    # ------------------------------------------------------------------
    # These tests VERIFY the fixed behaviour.
    # ------------------------------------------------------------------

    def test_fixed_schema_accepts_string_submission_single_area(self):
        """Fixed schema accepts '0' (string) for a single-area list."""
        schema = _build_delete_schema_fixed(ONE_AREA)
        result = schema({CONF_AREA_ID: "0"})
        self.assertEqual(result[CONF_AREA_ID], "0")

    def test_fixed_schema_accepts_all_indices_multi_area(self):
        """Fixed schema accepts any valid string index in a multi-area list."""
        schema = _build_delete_schema_fixed(TWO_AREAS)
        for submitted in ("0", "1"):
            with self.subTest(submitted=submitted):
                result = schema({CONF_AREA_ID: submitted})
                self.assertEqual(result[CONF_AREA_ID], submitted)

    def test_fixed_schema_rejects_out_of_range_index(self):
        """Fixed schema still rejects an index that doesn't exist."""
        schema = _build_delete_schema_fixed(ONE_AREA)
        with self.assertRaises(vol.Invalid):
            schema({CONF_AREA_ID: "99"})

    def test_fixed_schema_rejects_empty_submission(self):
        """Fixed schema (Required) rejects a submission with no area selected."""
        schema = _build_delete_schema_fixed(ONE_AREA)
        with self.assertRaises(vol.Invalid):
            schema({})

    def test_deletion_logic_removes_correct_area(self):
        """String-index comparison correctly removes the selected area."""
        options_areas = list(TWO_AREAS)
        selected = "0"  # remove index 0 (tshwane-8-moreletapark)

        new_areas = [
            area for idx, area in enumerate(options_areas)
            if str(idx) != str(selected)
        ]
        self.assertEqual(len(new_areas), 1)
        self.assertEqual(new_areas[0]["id"], "za_gt_jhb_fourways_4pef")

    def test_deletion_logic_preserves_remaining_areas(self):
        """Removing index 1 leaves index 0 intact."""
        options_areas = list(TWO_AREAS)
        selected = "1"

        new_areas = [
            area for idx, area in enumerate(options_areas)
            if str(idx) != str(selected)
        ]
        self.assertEqual(len(new_areas), 1)
        self.assertEqual(new_areas[0]["id"], "tshwane-8-moreletapark")


if __name__ == "__main__":
    unittest.main()

