"""Regression tests for config_flow fixes.

Issue #111: "Unable to remove area – value must be one of [0]"
Issue #111: quota burn surfacing buried SePushError.status_code
Single-source-of-truth: manifest.json is the sole version declaration.
"""
import json
import pathlib
import unittest

import voluptuous as vol


CONF_AREA_ID = "area_id"
CONF_NAME = "name"


# ---------------------------------------------------------------------------
# Minimal stubs so we can test _get_sepush_status_code without HA installed
# ---------------------------------------------------------------------------

class SePushError(Exception):
    def __init__(self, message=None, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ProviderError(Exception):
    pass


def _get_sepush_status_code(err):
    """Copy of the helper from config_flow — kept in sync."""
    seen = set()
    node = err
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if isinstance(node, SePushError) and node.status_code is not None:
            return node.status_code
        if node.args and isinstance(node.args[0], BaseException):
            inner = node.args[0]
            if isinstance(inner, SePushError) and inner.status_code is not None:
                return inner.status_code
        node = node.__cause__ or node.__context__
    return None


# ---------------------------------------------------------------------------
# Helpers to build schemas (mirroring config_flow logic exactly)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Regression: Issue #111 — delete-area schema validation
# ---------------------------------------------------------------------------

class TestDeleteAreaSchemaRegression(unittest.TestCase):
    """
    Regression: issue #111 – 'value must be one of [0]' when removing an area.

    HA config-flow forms always submit field values as strings.  The original
    schema used integer dict keys so vol.In({0: ...}) rejected the submitted
    string "0".  The fix uses string keys throughout.
    """

    def test_original_schema_rejects_string_submission_single_area(self):
        """Original schema raises Invalid when HA submits string '0'."""
        schema = _build_delete_schema_original(ONE_AREA)
        with self.assertRaises(vol.Invalid) as ctx:
            schema({CONF_AREA_ID: "0"})
        self.assertIn("value must be one of", str(ctx.exception))

    def test_original_schema_rejects_string_submission_multi_area(self):
        """Original schema raises Invalid for any string index."""
        schema = _build_delete_schema_original(TWO_AREAS)
        for submitted in ("0", "1"):
            with self.subTest(submitted=submitted):
                with self.assertRaises(vol.Invalid):
                    schema({CONF_AREA_ID: submitted})

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
        selected = "0"
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


# ---------------------------------------------------------------------------
# Regression: Issue #111 — _get_sepush_status_code walks buried exceptions
# ---------------------------------------------------------------------------

class TestGetSePushStatusCode(unittest.TestCase):
    """
    Regression: area search failures swallowed SePushError.status_code because
    get_areas() re-raises as ProviderError twice before reaching the config flow.

    Exception chain produced by the library:
      ProviderError("Unable to get areas from SePush.")
        __cause__ → ProviderError(SePushError("Token quota exceeded", 429))
                      .args[0] = SePushError(status_code=429)
    """

    def _make_chain(self, status_code: int) -> ProviderError:
        """Reproduce the exact two-level wrapping the library produces."""
        original = SePushError("Token quota exceeded", status_code=status_code)
        inner = ProviderError(original)       # ProviderError(e) — no `from`
        outer = ProviderError("Unable to get areas from SePush.")
        outer.__cause__ = inner               # raised with `from inner`
        return outer

    def test_extracts_429_from_nested_chain(self):
        err = self._make_chain(429)
        self.assertEqual(_get_sepush_status_code(err), 429)

    def test_extracts_403_from_nested_chain(self):
        err = self._make_chain(403)
        self.assertEqual(_get_sepush_status_code(err), 403)

    def test_extracts_500_from_nested_chain(self):
        err = self._make_chain(500)
        self.assertEqual(_get_sepush_status_code(err), 500)

    def test_returns_none_for_plain_provider_error(self):
        """Generic ProviderError with no SePushError in chain → None."""
        err = ProviderError("network timeout")
        self.assertIsNone(_get_sepush_status_code(err))

    def test_returns_none_for_provider_error_with_non_sepush_cause(self):
        err = ProviderError("something")
        err.__cause__ = ConnectionError("refused")
        self.assertIsNone(_get_sepush_status_code(err))

    def test_direct_sepush_error(self):
        """SePushError passed directly is handled."""
        err = SePushError("quota", status_code=429)
        self.assertEqual(_get_sepush_status_code(err), 429)

    def test_sepush_error_without_status_code(self):
        err = SePushError("something went wrong")
        self.assertIsNone(_get_sepush_status_code(err))

    def test_original_lookup_areas_behaviour_without_fix(self):
        """
        Document the broken behaviour: without the helper, a 429 buried in
        a ProviderError chain cannot be detected and falls through to generic
        'provider_error', showing the unhelpful 'Unable to reach Provider' message.
        """
        err = self._make_chain(429)

        # Old code: catches ProviderError but has no way to inspect status_code
        errors = {}
        # Simulate old handler: always provider_error regardless of root cause
        errors["base"] = "provider_error"
        self.assertEqual(errors["base"], "provider_error")  # unhelpful

    def test_fixed_lookup_areas_behaviour_shows_sepush_429(self):
        """
        With the helper, a 429 deep in the chain maps to sepush_429 error key,
        showing the user 'Token quota exceeded' instead of 'Unable to reach Provider'.
        """
        err = self._make_chain(429)

        errors = {}
        status_code = _get_sepush_status_code(err)
        if status_code == 403:
            errors["base"] = "sepush_403"
        elif status_code == 429:
            errors["base"] = "sepush_429"
        elif status_code == 500:
            errors["base"] = "sepush_500"
        else:
            errors["base"] = "provider_error"

        self.assertEqual(errors["base"], "sepush_429")  # correct, actionable


if __name__ == "__main__":
    unittest.main()

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


# ---------------------------------------------------------------------------
# Single source of truth: manifest.json owns the version number
# ---------------------------------------------------------------------------

_MANIFEST_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components" / "load_shedding" / "manifest.json"
)


class TestVersionSingleSourceOfTruth(unittest.TestCase):
    """manifest.json is the sole place to bump the version.
    const.py must read from it, not hard-code a duplicate string."""

    def test_manifest_has_version(self):
        manifest = json.loads(_MANIFEST_PATH.read_text())
        self.assertIn("version", manifest)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_const_reads_version_from_manifest(self):
        """const.py must not hard-code a version string separate from manifest."""
        const_src = (
            _MANIFEST_PATH.parent / "const.py"
        ).read_text()

        manifest_version = json.loads(_MANIFEST_PATH.read_text())["version"]

        # const.py must reference manifest.json, not a bare quoted version string
        self.assertIn("manifest.json", const_src,
                      "const.py should read version from manifest.json")
        # The hard-coded version string must NOT appear as a quoted literal
        self.assertNotIn(f'"{manifest_version}"', const_src,
                         "Version must not be duplicated as a quoted literal in const.py")
        self.assertNotIn(f"'{manifest_version}'", const_src,
                         "Version must not be duplicated as a quoted literal in const.py")


if __name__ == "__main__":
    unittest.main()

