# Code Review Report — Load Shedding integration

*Reviewer perspective: Home Assistant Core. Scope: commits `1f271a9`, `46f97e9`, `c90fa35`, `e1760d1`, `e2daae3`, plus surrounding code.*
*Date: 2026-06-18*

Existing suite status: `19 passed` — but it only covers `config_flow`; **none of today's changed modules are tested.**

---

## 🔴 HIGH — Regression introduced in `c90fa35` (#54): stage sensor `end_time`/`next_*` broken

**Finding.** `get_sensor_attrs()` is shared by **both** the area sensor *and* the stage sensor. The #54 change makes it walk `_continuous_block_end()` across back-to-back slots. That is correct for the **area forecast** (contiguous slots = one continuous outage), but **wrong for the stage sensor's `planned` list**, which is *contiguous by construction* — `async_update_stage()` sets `planned[i].end_time` to the exact same timestamp as `planned[i+1].start_time` (verified at `__init__.py:274`).

**Verified impact** (simulation): for a stage sensor with planned 2→4→6 transitions:
- `end_time`/`ends_in` jumps from the correct "+2h" (when the current stage changes) to **"+7 days 6h"** (the sentinel end of the whole sequence).
- `next_stage` / `next_start_time` / `next_end_time` are **lost** (`next_index` runs off the end of the list).

**Plan.** Make continuous-block extension opt-in per caller:
- Add a parameter, e.g. `get_sensor_attrs(forecast, stage=…, merge_contiguous=False)`.
- Pass `merge_contiguous=True` only from `LoadSheddingAreaSensorEntity.extra_state_attributes`; keep `False` for the stage sensor so stage boundaries and `next_*` are preserved.
- Guard with regression tests for both callers (below).

---

## 🟠 MEDIUM

### M1 — Calendar multi-stage merge now spans different areas (`46f97e9`)
The refactor moved the merge out of the per-area loop into `_build_events()`, which aggregates **all areas** into one list, sorts by `start`, then merges any `prev.end == event.start`. For users with **multiple areas** + `multi_stage_events`, adjacent slots from *different locations* can be merged into a single event, and the merged event keeps only the first area's `location`. The pre-refactor code merged within each area.

**Plan.** Merge per `location` (group events by area before merging), or only merge when `prev.location == event.location`. Add a multi-area calendar test.

### M2 — `#31` restore doesn't help stage sensors when quota is exhausted at startup
`async_setup_entry` creates stage entities by iterating `stage_coordinator.data`. If the first refresh returns `{}` (out of quota), **no stage entities are created at all**, so the restore logic added in `e2daae3` never runs for them — they disappear until a successful poll + reload. (Area entities are fine: they're built from configured areas.)

**Plan.** Create stage entities from a stable source (e.g. configured providers / restored entity registry entries) rather than live coordinator data, so they can restore. At minimum, document the limitation. Add a test that simulates an empty first refresh.

### M3 — No automated coverage for the changed modules
`sensor.py`, `calendar.py`, and `__init__.py` (coordinators) have **zero tests**. Every fix today (throttle, state clearing, end-time, merge, restore) is unverified in CI and at risk of silent regression — exactly how the #54 stage regression slipped in.

**Plan.** See the **Test Plan** section.

### M4 — `tests/test_config_flow.py` is duplicated
Lines ~244–400 are a verbatim duplicate of 1–242 (second `import unittest`, second `TestDeleteAreaSchemaRegression`, second `if __name__ == "__main__"`). The later class definitions silently shadow the earlier ones. Maintenance hazard and misleading coverage counts.

**Plan.** Delete the duplicated block; keep one copy. Pure cleanup, no behavior change.

---

## 🟢 LOW / NITS

- **L1 — Dead state in calendar.** `self._event` is now vestigial (the `event` property computes live); `_handle_coordinator_update` still assigns it. Remove `_event` to avoid confusion.
- **L2 — `nxt_index` clarity.** In `get_sensor_attrs`, `nxt_index` is `None`-initialized; it's always set when `nxt` is truthy, but add an explicit guard/assert before `_continuous_block_end(forecast, nxt_index)` for readability and static analysis.
- **L3 — Empty `forecast_calendar` always emitted.** It isn't in `CLEAN_DATA`, so an empty `[]` attribute is always present. Add it (and `forecast`-style empties) to `CLEAN_DATA` for tidiness.
- **L4 — Micro-perf in `async_area_forecast`.** `config_entry.options.get(CONF_MIN_EVENT_DURATION)` is read inside nested loops; hoist once per call. Pre-existing.
- **L5 — Micro-perf in calendar.** `event` property rebuilds + sorts all events on every read; fine for current data sizes, but could be memoized off `_handle_coordinator_update`.

---

## ✅ Confirmed-correct (no action)
- `1f271a9` (#61/#71): `.total_seconds()` fix is correct and the right API.
- `46f97e9` area `native_value`: the default-OFF rewrite is sound (validated across 6 cases).
- `e1760d1` `merge_forecast`: merge/label-join/dedup logic validated.
- The `.values`→`.value` typo fix in #54 is a genuine latent-bug fix (kept, but note it's only fully effective once HIGH is resolved).

---

## 📋 Test Plan (to add coverage & lock regressions)

**Tooling.** The changed modules `import homeassistant` at module top, so they can't be imported bare. Two options:

1. **Target (recommended):** add `pytest-homeassistant-custom-component` + `homeassistant` as test deps and run real entity/coordinator tests; wire it into `.github/workflows/validate.yml` so the suite runs on CI.
2. **Interim (pragmatic, matches current `test_config_flow.py` style):** extract the already-pure helpers and test them directly. Even better, refactor the pure logic (`_continuous_block_end`, `merge_forecast`, `get_sensor_attrs`, `restorable_attrs`, the throttle calc) into a dependency-free `helpers.py` so tests import them without HA.

**Concrete cases to add:**

| Area | Cases |
|---|---|
| `get_sensor_attrs` | area: back-to-back extension; **stage: planned NOT merged + `next_*` preserved** (locks the HIGH fix); before/during/after; `next_stage` value correctness |
| `_continuous_block_end` | single slot; contiguous run; gap stops the walk; `next_index` correctness |
| `merge_forecast` | contiguous merge; stage-label join + dedup; gap → separate blocks; empty input |
| area `native_value` | empty / all-past (stuck-on regression) / ongoing / future / NO_LOAD_SHEDDING |
| calendar | clears to `None` when forecast empties; current vs next selection; `async_get_events` range filter; **multi-area merge keeps locations distinct** (locks M1) |
| coordinator throttle | elapsed >24h triggers refresh (locks #61/#71); <interval returns cache |
| `restorable_attrs` | whitelist keeps data attrs, drops reserved (`friendly_name`, `icon`, …) |
| `#31` startup | empty first refresh → entity restore path behaves (locks M2) |

**CI.** Ensure `validate.yml` (currently hassfest/HACS-oriented) also runs `pytest`, so these tests actually gate merges.

---

## Suggested remediation order
1. **HIGH** — fix `get_sensor_attrs` stage regression + add the stage/area test (most user-visible, introduced today).
2. **M4** — de-duplicate the test file (quick, unblocks trustworthy coverage numbers).
3. **M3** — stand up the test harness + helper extraction; add the table above.
4. **M1** — per-location calendar merge + test.
5. **M2** — stage-entity creation/restore robustness.
6. **L1–L5** — cleanups alongside the above.

---

## Resolution status (updated 2026-06-18)

| Finding | Status | Commit |
|---|---|---|
| Harness (pytest + conftest) | ✅ done | `0d79dbc` |
| M4 — duplicated test file | ✅ done | `b2ef999` |
| M3 — extract pure logic + tests | ✅ done | `cc57618` |
| **HIGH** — stage-sensor merge regression | ✅ fixed + tests | `bdff55b` |
| M1 — calendar cross-area merge | ✅ fixed + tests | `bd19aa0` |
| L1 — dead `_event` field | ✅ done | `6c16ea3` |
| L2 — `nxt_index` guard | ✅ resolved by M3 refactor (guard now in `helpers.summarize_forecast`) | `cc57618` |
| L3 — empty `forecast_calendar` attr | ✅ done | `bce25bd` |
| L4 — hoist `min_event_duration` lookup | ✅ done | `4a424a0` |
| CI — run pytest | ✅ done | `38c7c04` |
| **M2** — stage entities not created when first refresh is empty | ⏳ deferred — needs live HA e2e (no `homeassistant` in unit env) | — |
| L5 — memoise calendar `event` rebuild | ⏳ optional, deferred | — |

Test suite: **51 passed** (config-flow + helpers), runnable via `pytest tests/`.


