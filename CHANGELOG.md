he ext# Changelog

All notable changes to this integration will be documented in this file.

## [1.6.0] - 2026-06-08

### Added
- **Home Assistant Repairs issue for invalid area IDs** — when the coordinator detects
  that a configured area has a legacy v2 area ID (containing hyphens), it raises a
  Repairs issue in HA with the title *"Load Shedding area IDs need to be updated"*.
  The issue names the affected areas and provides step-by-step remediation instructions.
  The issue is automatically resolved the next time the integration loads with only
  valid v3 area IDs configured.

- **Per-area error isolation** — a single invalid or unreachable area no longer causes
  all other areas to stop updating.  Each area is fetched independently; failures are
  logged per-area and processing continues for the remaining areas.

- **Permanent-failure skip list** — areas with legacy v2 IDs (400 error, hyphen ID) are
  added to an in-memory skip list after the first failure.  They are not polled again
  in the same session, preventing quota burn from minute-by-minute retries.

- **User-Agent attribution** — all SePush HTTP requests now include:
  ```
  User-Agent: load_shedding/0.14.0 (ha_integration_load_shedding/1.6.0; homeassistant/2026.x.x)
  ```

### Changed
- `SePushError.status_code` is now used directly (instead of digging into
  `err.__cause__.args[0]`) to classify API errors in the config and options flows.

- `sepush_400` error message updated to hint at the v2→v3 area ID migration.

### Fixed
- Areas with legacy v2 hyphen-format IDs no longer spam the SePush API on every
  60-second poll, burning daily quota.

### Dependency
- Requires `load-shedding==0.14.0`.

---

## [1.5.3] - prior release

See repository history.

