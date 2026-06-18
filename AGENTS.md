# Agent Instructions — Load Shedding Integration

This repository is a **Home Assistant custom integration** that tracks load
shedding schedules via the [EskomSePush API](https://eskomsepush.gumroad.com/l/api).

## Repository layout

```
custom_components/load_shedding/   Integration source (the live component)
examples/
  automations/                     Example automation YAML files
  dashboards/                      Example Lovelace card YAML files
tests/                             pytest test suite
scripts/
  setup_dev.py                     One-command dev-container bootstrap (see below)
  setup_ha.py                      Lovelace dashboard setup (subset of setup_dev.py)
  test                             Shortcut to run the test suite
dev.sh                             Dev helpers (translations, hassfest)
```

The integration is **live-loaded** via a symlink when developed inside the
`ha.core` dev container:

```
config/custom_components/load_shedding → ../load_shedding/custom_components/load_shedding
```

## Dev-container bootstrap (after cloning)

Run once after cloning into `config/load_shedding/` with HA already running:

```bash
SEPUSH_API_KEY=<key> HA_TOKEN=<long-lived-token> python scripts/setup_dev.py
```

This is **idempotent** (safe to re-run). It:
1. Installs HACS into `config/custom_components/hacs`
2. Downloads the three frontend card JS files into `config/www/community/`
3. Writes the five example automations to `config/automations.yaml`
4. Registers the Lovelace resources, creates the **Load Shedding** dashboard, and
   populates it with all four example cards (customised for the installed entities)

After running, if HACS was newly installed: restart HA, then complete HACS setup
via **Settings → Devices & Services → Add Integration → HACS** (one-time GitHub
device login).

## Running tests

```bash
cd config/load_shedding
python3 -m pytest tests/
```

Or use the shortcut:

```bash
scripts/test
```

The test harness uses `pytest-homeassistant-custom-component` installed isolated
in the HA venv. Tests live in `tests/`; fixtures are in `conftest.py` (root) and
`tests/conftest.py`.

## Key conventions

### Integration structure

- Config-flow only; requires a SePush API key. Entry version is 5.
- **Coordinators** (`__init__.py`): `StageCoordinator`, `AreaCoordinator`,
  `QuotaCoordinator`. They do not receive `config_entry` as a constructor arg —
  HA auto-assigns it during setup.
- **Entities** (`sensor.py`, `calendar.py`): `RestoreSensor` + `CoordinatorEntity`.
  Entities restore their last-known attributes on HA restart so the forecast
  survives an API quota outage until the first successful poll (`#31`).
- Stage entities are created **lazily** from the SePush status payload (not at
  platform setup time), so they appear once data arrives even if the first poll
  is empty.

### Forecast logic

- `async_area_forecast()` intersects *planned* stages with the area's timetable
  schedule. Falls back to SePush `events` when no planned stages exist.
- This is **not** gated on the current stage — the forecast shows future slots
  even when the current stage is 0 (suspended).
- SePush provides at most 7 days of forecast data (`FORECAST_DAYS = 7`).
- `merge_forecast()` / `merge_contiguous` merges back-to-back timeslots so the
  area sensor shows a single continuous block rather than per-slot entries (`#54`).

### Entity IDs (this dev instance)

Entity IDs depend on which areas are configured. In the standard dev-container
setup there are currently four area sensors:

| Entity | Description |
|--------|-------------|
| `sensor.load_shedding_stage_eskom` | Eskom stage |
| `sensor.load_shedding_stage_capetown` | Cape Town stage |
| `sensor.load_shedding_area_za_gt_tsh_garsfontein_gaev` | Area sensor |
| `sensor.load_shedding_area_za_gt_tsh_lynnwoodglen_x049` | Area sensor |
| `sensor.load_shedding_area_za_gt_dc42_bedworthpark_h80w` | Area sensor |
| `sensor.load_shedding_area_za_gt_dc48_fourways_3nl2` | Area sensor |
| `sensor.load_shedding_sepush_api_quota` | API quota (count/limit) |
| `calendar.load_shedding_forecast` | Calendar entity |

Area IDs are in the SePush v3 format (`za_xx_...`). If areas are in the old v2
hyphen format, the integration raises a HA Repairs issue.

### Testing conventions

- `asyncio_mode = auto` (configured in `pytest.ini`).
- Key fixtures: `mock_sepush`, `build_config_entry`, `init_integration` (in
  `tests/conftest.py`); `enable_custom_integrations` autouse (in root
  `conftest.py`).
- `freezer` fixture must be typed as `FrozenDateTimeFactory` (from `freezegun.api`).
- Snapshot tests use Syrupy (`.ambr` files).
- Avoid branching in tests; use `pytest.mark.parametrize` + `pytest.param(id=...)`.

### Commit guidelines

- **Do not amend, squash, or rebase commits already pushed to an open PR.**
  Reviewers track per-commit diffs.
- Commit messages: imperative mood, reference issue/PR numbers where relevant.

### Code style

- Python 3.14+ — do not add `from __future__ import annotations` workarounds.
- Ruff for linting/formatting (`charliermarsh.ruff`).
- Keep comments minimal: explain *why* (non-obvious constraints, workarounds),
  never *what* the adjacent code does.
- Prefer direct key access (`data["key"]`) when the key is guaranteed to exist.
