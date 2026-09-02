#!/usr/bin/env python3
"""
Model scan, status, and cooldown management for aipass-auto-router.

Usage:
  python scripts/check_models.py --scan           # Discover models in active tab
  python scripts/check_models.py --status          # Show cooldown & availability
  python scripts/check_models.py --clear-cooldown  # Reset all cooldowns
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from aipass_bridge import AIPassBridge


async def main():
    parser = argparse.ArgumentParser(description="Model status & scan manager")
    parser.add_argument("--scan", action="store_true", help="Scan available models")
    parser.add_argument("--status", action="store_true", help="Show cooldown status")
    parser.add_argument("--clear-cooldown", action="store_true", help="Clear all cooldowns")
    args = parser.parse_args()

    bridge = AIPassBridge()

    if args.scan:
        models = await bridge.scan_models()
        print(f"Discovered {len(models)} models:")
        for m in models:
            classes = ", ".join(m.task_classes)
            print(f"  {m.id:30s}  classes={classes}  priority={m.priority}")
        return

    if args.status:
        print(f"{'Model':<30s}  {'Status':<12s}  {'Cooldown Until':<25s}  {'Errors':<6s}")
        print("=" * 80)
        for mid, m in sorted(bridge.status_mgr.models.items()):
            status = "available" if m.available and not m.cooldown_until else "cooldown"
            cd = m.cooldown_until or "-"
            print(f"{mid:<30s}  {status:<12s}  {cd:<25s}  {m.error_count:<6d}")
        return

    if args.clear_cooldown:
        for m in bridge.status_mgr.models.values():
            m.cooldown_until = None
            m.available = True
            m.error_count = 0
        bridge.status_mgr.save()
        print("All cooldowns cleared.")
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
