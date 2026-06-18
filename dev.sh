python -m script.translations develop --integration load_shedding
python -m script.hassfest

# One-command dev-container bootstrap (idempotent — safe to re-run):
#
#   HA_TOKEN=<long-lived-token> python scripts/setup_dev.py
#
# Installs HACS + frontend card JS files, writes example automations, and
# creates the Load Shedding Lovelace dashboard with all example cards.
# Requires HA to be running. See scripts/setup_dev.py for full details.