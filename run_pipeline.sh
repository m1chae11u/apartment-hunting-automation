#!/bin/bash
# Apartment hunting pipeline — scrape, filter, group, update sheet, notify.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

source .venv/bin/activate

echo "=== Step 1: Scrape ==="
python tools/scrape.py

echo "=== Step 2: Hard Filters ==="
python tools/process.py

echo "=== Step 3: Building Grouping ==="
python tools/group_buildings.py

echo "=== Step 4: Update Sheet ==="
python tools/update_sheet.py

echo "=== Step 5: Notify ==="
python tools/notify.py

echo "=== Pipeline complete ==="
