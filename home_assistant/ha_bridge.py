#!/usr/bin/env python3
"""Run the Home Assistant bridge (home_assistant/README.md).

    python home_assistant/ha_bridge.py --host homeassistant.local            # on the comma device
    python home_assistant/ha_bridge.py --replay data/sample/highway_following_30s.csv.gz --dry-run
    python home_assistant/ha_bridge.py --install-autostart                   # start it on every boot
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ars510_ha.bridge import main

if __name__ == "__main__":
    raise SystemExit(main())
