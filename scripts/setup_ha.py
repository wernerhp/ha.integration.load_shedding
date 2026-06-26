#!/usr/bin/env python3
"""Set up the Load Shedding dashboard on a running Home Assistant instance.

Registers the three frontend card resources, creates the "Load Shedding"
dashboard, and saves an Examples view containing all four example cards.
Area chips and period settings are updated to match what is actually installed.

Usage
-----
    HA_TOKEN=<long-lived-access-token> python scripts/setup_ha.py

Optional environment variables:
    HA_URL          Base URL of Home Assistant (default: http://localhost:8123)

The script is idempotent: re-running it updates the dashboard config without
creating duplicates.

Dependencies
------------
aiohttp and PyYAML are available in the HA dev-container venv:
    /home/vscode/.local/ha-venv/bin/python scripts/setup_ha.py

Frontend card JS files must already be present under config/www/community/.
Download them with:
    mkdir -p config/www/community/lovelace-mushroom
    curl -sL -o config/www/community/lovelace-mushroom/mushroom.js \\
        https://github.com/piitaya/lovelace-mushroom/releases/latest/download/mushroom.js

    mkdir -p config/www/community/atomic-calendar-revive
    curl -sL -o config/www/community/atomic-calendar-revive/atomic-calendar-revive.js \\
        https://github.com/totaldebug/atomic-calendar-revive/releases/latest/download/atomic-calendar-revive.js

    mkdir -p config/www/community/lovelace-html-jinja2-template-card
    curl -sL -o config/www/community/lovelace-html-jinja2-template-card/html-template-card.js \\
        https://raw.githubusercontent.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card/master/dist/html-template-card.js
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import aiohttp
import yaml

HA_URL = os.environ.get("HA_URL", "http://localhost:8123")
WS_URL = HA_URL.replace("http", "ws", 1) + "/api/websocket"
TOKEN = os.environ.get("HA_TOKEN", "")

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples" / "dashboards"

RESOURCES = [
    "/local/community/lovelace-mushroom/mushroom.js",
    "/local/community/atomic-calendar-revive/atomic-calendar-revive.js",
    "/local/community/lovelace-html-jinja2-template-card/html-template-card.js",
]

DASHBOARD_URL_PATH = "load-shedding"
DASHBOARD_TITLE = "Load Shedding"

# SePush provides at most 7 days of forecast data.
FORECAST_DAYS = 7


def get_states() -> list[dict]:
    req = urllib.request.Request(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    return json.load(urllib.request.urlopen(req, timeout=15))


def area_entity_ids(states: list[dict]) -> list[str]:
    return sorted(
        s["entity_id"]
        for s in states
        if s["entity_id"].startswith("sensor.load_shedding_area")
    )


def load_card(name: str, entity_map: dict[str, str]) -> dict:
    """Load a card YAML file, applying entity ID substitutions."""
    text = (EXAMPLES_DIR / name).read_text(encoding="utf-8")
    for old, new in entity_map.items():
        text = text.replace(old, new)
    return yaml.safe_load(text)


def apply_customisations(cards: list[dict], area_sensors: list[str]) -> None:
    """Apply the period and chip customisations to the card list in-place."""
    for card in cards:
        t = card.get("type", "")
        if t == "custom:mushroom-chips-card":
            # Keep non-area chips (quota template chip + stage entity chip),
            # then append one entity chip per installed area sensor.
            kept = [
                ch
                for ch in card.get("chips", [])
                if not (
                    ch.get("type") == "entity"
                    and str(ch.get("entity", "")).startswith("sensor.load_shedding_area")
                )
            ]
            for eid in area_sensors:
                kept.append(
                    {"type": "entity", "entity": eid, "hold_action": {"action": "more-info"}}
                )
            card["chips"] = kept

        elif t == "custom:atomic-calendar-revive":
            card["maxDaysToShow"] = FORECAST_DAYS

        elif t == "custom:html-template-card":
            card["content"] = re.sub(
                r"set number_of_days = \d+",
                f"set number_of_days = {FORECAST_DAYS}",
                card.get("content", ""),
            )


class WS:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ws = ws
        self._ids = itertools.count(1)

    async def cmd(self, **payload) -> dict:
        msg_id = next(self._ids)
        await self._ws.send_json({"id": msg_id, **payload})
        while True:
            data = await self._ws.receive_json()
            if data.get("id") == msg_id and data.get("type") == "result":
                return data


async def main() -> int:
    if not TOKEN:
        print("Error: set HA_TOKEN to a long-lived access token.", file=sys.stderr)
        return 1

    print("Fetching installed area sensors …")
    states = get_states()
    areas = area_entity_ids(states)
    if not areas:
        print("Warning: no area sensors found; chips chip will be empty.")

    # Build an entity map from the example placeholder to the first real area
    # sensor (the example YAML uses a single hard-coded Tshwane area).
    example_area = "sensor.load_shedding_area_tshwane_3_garsfonteinext8"
    entity_map: dict[str, str] = {}
    if areas:
        entity_map[example_area] = areas[0]

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL) as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                print("Auth failed:", auth, file=sys.stderr)
                return 1

            client = WS(ws)

            # 1) Register Lovelace resources
            existing = await client.cmd(type="lovelace/resources")
            have = {item["url"] for item in existing.get("result", [])}
            for url in RESOURCES:
                if url in have:
                    print(f"resource already registered: {url}")
                    continue
                res = await client.cmd(
                    type="lovelace/resources/create", res_type="module", url=url
                )
                print(f"resource registered {url}: {res.get('success')}")

            # 2) Ensure the dashboard exists
            dashboards = await client.cmd(type="lovelace/dashboards/list")
            paths = {d["url_path"] for d in dashboards.get("result", [])}
            if DASHBOARD_URL_PATH not in paths:
                res = await client.cmd(
                    type="lovelace/dashboards/create",
                    url_path=DASHBOARD_URL_PATH,
                    title=DASHBOARD_TITLE,
                    icon="mdi:transmission-tower-off",
                    show_in_sidebar=True,
                    require_admin=False,
                )
                ok = res.get("success")
                print(f"dashboard created: {ok}")
                if not ok:
                    print(json.dumps(res, indent=2), file=sys.stderr)
                    return 1
            else:
                print(f"dashboard already exists: {DASHBOARD_URL_PATH}")

            # 3) Build, customise, and save the view config
            cards = [
                load_card("mushroom_chips.yaml", entity_map),
                load_card("status_alert.yaml", entity_map),
                load_card("calendar.yaml", entity_map),
                load_card("esp_status_bar.yaml", entity_map),
            ]
            apply_customisations(cards, areas)

            config = {
                "title": DASHBOARD_TITLE,
                "views": [
                    {
                        "title": "Examples",
                        "path": "examples",
                        "icon": "mdi:flash",
                        "cards": cards,
                    }
                ],
            }
            res = await client.cmd(
                type="lovelace/config/save",
                url_path=DASHBOARD_URL_PATH,
                config=config,
            )
            ok = res.get("success")
            print(f"dashboard config saved: {ok}")
            if not ok:
                print(json.dumps(res, indent=2), file=sys.stderr)
                return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
