#!/usr/bin/env python3
"""Bootstrap a fresh dev-container clone to match the full local dev setup.

Run this once after cloning the repo into the HA core dev container at
config/load_shedding/ and starting Home Assistant.  It is fully idempotent
and safe to re-run.

What it does
------------
1. Installs HACS into config/custom_components/hacs (latest release zip).
2. Downloads the three frontend card JS files into config/www/community/:
   - lovelace-mushroom
   - atomic-calendar-revive
   - HTML Jinja2 Template card
3. Writes the five example automations (with sidebar/persistent notifications)
   to config/automations.yaml and reloads them via the HA API.
4. Registers the Lovelace resources, creates the Load Shedding dashboard and
   saves the four example cards (via scripts/setup_ha.py).

Prerequisites
-------------
- Home Assistant is running at HA_URL (default http://localhost:8123).
- HA_TOKEN environment variable is set to a long-lived access token.
- The repo is cloned at config/load_shedding/ inside the HA config directory.
  (Symlink config/custom_components/load_shedding → ../load_shedding/custom_components/load_shedding
   must already exist — see dev container setup notes.)

Usage
-----
    HA_TOKEN=<token> python scripts/setup_dev.py

Optional environment variables:
    HA_URL          Base URL (default: http://localhost:8123)
    HA_CONFIG_DIR   Path to HA config directory (default: ../.. relative to this script,
                    i.e. config/ when the repo lives at config/load_shedding/)
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
# Default: the repo lives at <ha_config>/load_shedding/, so config dir is one
# level above the repo root (REPO_ROOT.parent).
HA_CONFIG_DIR = Path(
    os.environ.get("HA_CONFIG_DIR", str(REPO_ROOT.parent))
).resolve()

HA_URL = os.environ.get("HA_URL", "http://localhost:8123")
TOKEN = os.environ.get("HA_TOKEN", "")

CUSTOM_COMPONENTS = HA_CONFIG_DIR / "custom_components"
WWW = HA_CONFIG_DIR / "www" / "community"
AUTOMATIONS_YAML = HA_CONFIG_DIR / "automations.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download(url: str) -> bytes:
    print(f"  downloading {url.split('/')[-1]} …")
    req = urllib.request.Request(url, headers={"User-Agent": "setup_dev.py"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def latest_release_asset(repo: str, filename: str) -> str:
    """Return the browser_download_url for a specific asset in the latest release."""
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    data = json.loads(download(api))
    for asset in data.get("assets", []):
        if asset["name"] == filename:
            return asset["browser_download_url"]
    raise RuntimeError(f"Asset {filename!r} not found in {repo} latest release")


def ha_post(path: str, payload: dict) -> int:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{HA_URL}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


# ---------------------------------------------------------------------------
# Step 1 — HACS
# ---------------------------------------------------------------------------

def install_hacs() -> None:
    dest = CUSTOM_COMPONENTS / "hacs"
    manifest = dest / "manifest.json"
    if manifest.exists():
        version = json.loads(manifest.read_text())["version"]
        print(f"[1/4] HACS already installed (v{version}), skipping.")
        return

    print("[1/4] Installing HACS …")
    url = "https://github.com/hacs/integration/releases/latest/download/hacs.zip"
    data = download(url)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)
    version = json.loads((dest / "manifest.json").read_text())["version"]
    print(f"      HACS v{version} installed → {dest}")
    print("      ⚠️  Restart HA, then complete HACS setup via Settings → Integrations → HACS")
    print("         (requires one-time GitHub device login)")


# ---------------------------------------------------------------------------
# Step 2 — Frontend card JS files
# ---------------------------------------------------------------------------

CARDS = [
    {
        "dir": "lovelace-mushroom",
        "file": "mushroom.js",
        "url": "https://github.com/piitaya/lovelace-mushroom/releases/latest/download/mushroom.js",
    },
    {
        "dir": "atomic-calendar-revive",
        "file": "atomic-calendar-revive.js",
        "url": "https://github.com/totaldebug/atomic-calendar-revive/releases/latest/download/atomic-calendar-revive.js",
    },
    {
        "dir": "lovelace-html-jinja2-template-card",
        "file": "html-template-card.js",
        "url": "https://raw.githubusercontent.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card/master/dist/html-template-card.js",
    },
]


def install_cards() -> None:
    print("[2/4] Installing frontend card resources …")
    for card in CARDS:
        dest = WWW / card["dir"] / card["file"]
        if dest.exists():
            print(f"      {card['file']} already present, skipping.")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(download(card["url"]))
        print(f"      {card['file']} → {dest}")


# ---------------------------------------------------------------------------
# Step 3 — Automations
# ---------------------------------------------------------------------------

AUTOMATIONS_YAML_CONTENT = """\
- id: ls_example_reload
  alias: Load Shedding Reload
  description: 'Reloads the integration every night to work around Issue #70/#71'
  triggers:
  - trigger: time
    at: 00:00:00
  conditions: []
  actions:
  - variables:
      config_entry: '{{ config_entry_id(integration_entities("Load Shedding") | first) }}'
  - alias: Config entry found?
    if:
    - condition: template
      value_template: '{{ config_entry != None }}'
    then:
    - action: homeassistant.reload_config_entry
      data:
        entry_id: '{{ config_entry }}'
    else:
    - stop: Config entry for Load Shedding not found
      error: true
  mode: single

- id: ls_example_stage
  alias: Load Shedding (Stage)
  description: Sidebar notification when the load shedding stage changes.
  trigger:
  - platform: state
    entity_id:
    - sensor.load_shedding_stage_eskom
    attribute: stage
  condition:
  - condition: not
    conditions:
    - condition: state
      entity_id: sensor.load_shedding_stage_eskom
      state: unavailable
  action:
  - service: persistent_notification.create
    data:
      notification_id: load_shedding_stage
      title: Load Shedding
      message: >-
        {% if is_state_attr('sensor.load_shedding_stage_eskom', 'stage', 0) %}
          Suspended
        {% else %}
          Stage {{ state_attr('sensor.load_shedding_stage_eskom', 'stage') }}
        {% endif %}
  mode: restart

- id: ls_example_start_end
  alias: Load Shedding (Start/End)
  description: Sidebar notification when load shedding starts for your area.
  trigger:
  - platform: state
    entity_id:
    - sensor.load_shedding_area_REPLACE_AREA
    to: 'on'
    from: 'off'
  condition:
  - condition: numeric_state
    entity_id: sensor.load_shedding_stage_eskom
    attribute: stage
    above: 0
  action:
  - service: persistent_notification.create
    data:
      notification_id: load_shedding_active
      title: Load Shedding
      message: >-
        Load Shedding has started. Power off until
        {{ (state_attr('sensor.load_shedding_area_REPLACE_AREA', 'end_time')
            | as_datetime | as_local).strftime('%H:%M (%Z)') }}.
  mode: single

- id: ls_example_warning
  alias: Load Shedding (Warning)
  description: Sidebar notification 15 minutes before load shedding starts.
  trigger:
  - platform: numeric_state
    entity_id: sensor.load_shedding_area_REPLACE_AREA
    attribute: starts_in
    below: 15
  condition:
  - condition: numeric_state
    entity_id: sensor.load_shedding_stage_eskom
    attribute: stage
    above: 0
  action:
  - service: persistent_notification.create
    data:
      notification_id: load_shedding_warning
      title: Load Shedding
      message: Load Shedding starts in 15 minutes.
  mode: single

- id: ls_example_warning_2hr
  alias: Load Shedding (Warning) (2hr)
  description: Sidebar notification 2 hours before load shedding starts.
  trigger:
  - platform: numeric_state
    entity_id: sensor.load_shedding_area_REPLACE_AREA
    attribute: starts_in
    below: 120
  condition:
  - condition: numeric_state
    entity_id: sensor.load_shedding_stage_eskom
    attribute: stage
    above: 0
  action:
  - service: persistent_notification.create
    data:
      notification_id: load_shedding_warning_2hr
      title: Load Shedding
      message: Load Shedding starts in 2 hours.
  mode: single
"""


def get_area_sensor() -> str:
    """Return the entity_id of the first installed area sensor."""
    req = urllib.request.Request(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    states = json.load(urllib.request.urlopen(req, timeout=15))
    areas = sorted(
        s["entity_id"]
        for s in states
        if s["entity_id"].startswith("sensor.load_shedding_area")
    )
    if not areas:
        raise RuntimeError(
            "No area sensors found. Ensure the Load Shedding integration is configured."
        )
    return areas[0]


def install_automations() -> None:
    print("[3/4] Writing automations …")
    area = get_area_sensor()
    # Strip "sensor." prefix to get the part after sensor.load_shedding_area_
    area_suffix = area.removeprefix("sensor.load_shedding_area_")
    content = AUTOMATIONS_YAML_CONTENT.replace("REPLACE_AREA", area_suffix)

    existing = AUTOMATIONS_YAML.read_text(encoding="utf-8") if AUTOMATIONS_YAML.exists() else ""
    if "ls_example_reload" in existing:
        print(f"      automations already present in {AUTOMATIONS_YAML}, skipping.")
    else:
        AUTOMATIONS_YAML.write_text(content, encoding="utf-8")
        print(f"      wrote 5 automations → {AUTOMATIONS_YAML}")

    print("      reloading automations …")
    ha_post("/api/services/automation/reload", {})
    print("      done.")


# ---------------------------------------------------------------------------
# Step 4 — Dashboard (delegates to setup_ha.py)
# ---------------------------------------------------------------------------

def install_dashboard() -> None:
    print("[4/4] Setting up Lovelace dashboard …")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "setup_ha", SCRIPT_DIR / "setup_ha.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import asyncio
    rc = asyncio.run(mod.main())
    if rc != 0:
        raise RuntimeError("setup_ha.py failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if not TOKEN:
        print("Error: set HA_TOKEN to a long-lived access token.", file=sys.stderr)
        print("  Create one in HA under Profile → Security → Long-Lived Access Tokens.",
              file=sys.stderr)
        return 1

    print(f"HA config dir : {HA_CONFIG_DIR}")
    print(f"HA URL        : {HA_URL}")
    print()

    try:
        install_hacs()
        install_cards()
        install_automations()
        install_dashboard()
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print()
    print("Bootstrap complete.")
    print("If HACS was newly installed, restart HA then open")
    print("  Settings → Devices & Services → Add Integration → HACS")
    print("and complete the GitHub device login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
