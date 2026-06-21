# Changelog

All notable changes to this integration will be documented in this file.

## [1.7.0] - 2026-06-21

### Added
- **Temporary API outages are now surfaced as a Repairs issue.** Any failed stage
  poll raises a repair: auth/quota errors (`400`/`403`/`429`) as an actionable
  `sepush_api_failure` (error), and transient server/network/unexpected failures
  (`5xx`, timeouts, malformed payloads) as a `sepush_api_unavailable` (warning).
  Both clear automatically once data is fetched again.
- **Version context in logs.** Error and exception logs now include the integration
  and Home Assistant versions (e.g. `[load_shedding 1.7.0, Home Assistant 2026.6.x]`)
  — and the area name/ID or search term where relevant — so user-submitted logs are
  self-identifying.

### Fixed
- **No more generic "Unknown error" in the config flow** ([#116](https://github.com/wernerhp/ha.integration.load_shedding/issues/116)).
  The token-validation steps now catch unexpected (non-`SePushError`) failures,
  log them, and surface a friendly `unknown` error instead of letting them bubble
  up to Home Assistant as "Unknown error occurred" with nothing in the integration
  log. Area selection is also guarded against an unresolved selection (it returns
  to search instead of raising `AttributeError`).
- **A malformed payload for one zone/area no longer aborts the whole update.**
  Per-zone and per-area parsing is wrapped so a single bad entry is logged (with a
  traceback and the offending area) and skipped, while the others still update.
- **Transient errors no longer wipe data or stay hidden.** The area coordinator
  keeps the previously-fetched schedules on a transient failure instead of clearing
  them, and the quota sensor tolerates a transient `rate_limit()` read error instead
  of breaking its state update. Setup failures (missing API key or no areas) are now
  logged explaining what to fix.

### Changed
- **Dependency bump to `load_shedding==0.15.1`.** The library now guarantees that
  every public `SePush` method raises only `SePushError` (with a `status_code`) for
  any network, HTTP, or body-parsing failure — including an HTTP `200` response
  whose body is not JSON, which previously escaped as `json.JSONDecodeError`. The
  provider layer also gained shape guards and preserves the exception chain
  (`raise ProviderError(...) from e`), so the integration can still recover the
  underlying SePush HTTP status code.

### Security
- `load_shedding==0.15.1` requires `certifi~=2026.6.17`, `urllib3[secure]>=2.7.0`
  and `beautifulsoup4~=4.15.0`, replacing the outdated `certifi 2021.x` / `bs4 4.9.x`
  pins that carried known CVEs.

### Dependency
- Requires `load_shedding==0.15.1`.

---

## [1.6.4] - 2026-06-19

### Changed
- **Dependency bump to `load_shedding==0.15.0`** — migrates the underlying SePush client
  to the **Business API v3.1**. This is a transparent, fully backward-compatible change
  for the integration:
  - Base URL moves from `…/business/3.0` to `…/business/3.1`.
  - The auth header is normalised to lowercase `token`.
  - Quota is now read from the `x-ratelimit-*` response headers (v3.1 removed the
    `/api_allowance` endpoint), which the shared SePush client caches on every call.
- **Quota now read from cached rate-limit headers.** The quota sensor reads
  `sepush.rate_limit()` (a pure in-memory read of the cached `x-ratelimit-*`
  headers populated by the hourly stage poll on the same client instance).
  This removes the redundant hourly quota request entirely.
- **Token validation uses `rate_limit(True)`** (a free, unmetered request) in the
  config and options flows, replacing the now-removed `check_allowance()` call.
  Each config entry has its own SePush client instance, so rate-limit caches are
  isolated per API key.

### Fixed
- **Quota sensor hardening** — the SePush API Quota sensor now coerces a missing/`None`
  credit count to `0` (`int(rate_limit.get("used") or 0)`) instead of raising
  `TypeError`, guarding against a `200` response that omits the `x-ratelimit-used` header.

### Dependency
- Requires `load_shedding==0.15.0`.

---

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
- Requires `load_shedding==0.14.0`.

---

## [1.5.3] - prior release

See repository history.

