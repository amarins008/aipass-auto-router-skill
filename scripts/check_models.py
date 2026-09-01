#!/usr/bin/env python3
"""
AI-Pass Auto Router - Model Availability Scanner & Cooldown Manager
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

try:
    import websockets
    import aiohttp
except ImportError:
    print("Missing deps: pip install websockets aiohttp pydantic")
    sys.exit(1)

# ─── Configuration ──────────────────────────────────────────────
CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
TARGET_URL_PATTERN = "de.aipass.net/chat"
SKILL_DIR = Path(__file__).parent.parent
STATE_DIR = SKILL_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
MODEL_STATUS_FILE = STATE_DIR / "model_status.json"
ROUTING_FILE = SKILL_DIR / "references" / "routing.md"


@dataclass
class ModelInfo:
    id: str
    name: str
    task_classes: List[str] = None
    priority: int = 999
    available: bool = True
    cooldown_until: Optional[str] = None
    last_used: Optional[str] = None
    error_count: int = 0

    def __post_init__(self):
        if self.task_classes is None:
            self.task_classes = []


class ModelStatusManager:
    def __init__(self, status_file: Path):
        self.status_file = status_file
        self.models: Dict[str, ModelInfo] = {}
        self.load()

    def load(self):
        if self.status_file.exists():
            try:
                data = json.loads(self.status_file.read_text(encoding="utf-8"))
                self.models = {k: ModelInfo(**v) for k, v in data.items()}
            except Exception:
                self.models = {}
        self._expire_cooldowns()

    def save(self):
        self._expire_cooldowns()
        data = {k: asdict(v) for k, v in self.models.items()}
        self.status_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _expire_cooldowns(self):
        now = datetime.now()
        for m in self.models.values():
            if m.cooldown_until:
                try:
                    cd = datetime.fromisoformat(m.cooldown_until)
                    if cd <= now:
                        m.cooldown_until = None
                        m.available = True
                except Exception:
                    m.cooldown_until = None

    def set_cooldown(self, model_id: str, minutes: int = 15):
        if model_id in self.models:
            m = self.models[model_id]
            m.cooldown_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
            m.available = False
            m.error_count += 1
            self.save()
            print(f"Set {minutes}min cooldown for {model_id} (until {m.cooldown_until})")
        else:
            print(f"Model {model_id} not found in registry", file=sys.stderr)

    def clear_cooldown(self, model_id: str):
        if model_id in self.models:
            m = self.models[model_id]
            m.cooldown_until = None
            m.available = True
            self.save()
            print(f"Cleared cooldown for {model_id}")
        else:
            print(f"Model {model_id} not found in registry", file=sys.stderr)

    def update_from_scan(self, discovered: List[ModelInfo]):
        for m in discovered:
            if m.id not in self.models:
                self.models[m.id] = m
            else:
                existing = self.models[m.id]
                existing.name = m.name
                existing.task_classes = m.task_classes
                existing.priority = m.priority
        self.save()

    def print_status(self):
        self._expire_cooldowns()
        if not self.models:
            print("No models registered. Run --scan first.")
            return

        print(f"\n{'Model ID':<30} {'Name':<25} {'Status':<12} {'Classes':<25} {'Cooldown Until':<25} {'Last Used':<25}")
        print("-" * 150)
        for m in sorted(self.models.values(), key=lambda x: (not x.available, x.priority)):
            status = "AVAILABLE" if m.available else "COOLDOWN"
            if m.error_count > 0:
                status += f" (errors: {m.error_count})"
            classes = ", ".join(m.task_classes) if m.task_classes else "—"
            cd = m.cooldown_until or "—"
            lu = m.last_used or "—"
            print(f"{m.id:<30} {m.name:<25} {status:<12} {classes:<25} {cd:<25} {lu:<25}")

    def print_routing(self):
        """Print task-class to model mapping."""
        if not ROUTING_FILE.exists():
            print(f"Routing file not found: {ROUTING_FILE}")
            return

        content = ROUTING_FILE.read_text(encoding="utf-8")
        print("\n=== Task-Class Routing Map ===")
        current_class = None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("## "):
                current_class = line[3:].strip()
                print(f"\n{current_class}:")
            elif line.startswith("- ") and current_class:
                model_id = line[2:].strip().split()[0]
                model = self.models.get(model_id)
                status = "✓" if model and model.available else "✗" if model else "?"
                print(f"  {status} {model_id}")


class CDPClient:
    def __init__(self, host: str = CDP_HOST, port: int = CDP_PORT):
        self.host = host
        self.port = port
        self.ws = None
        self.target = None
        self._msg_id = 0

    async def connect(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.host}:{self.port}/json/list") as resp:
                    targets = await resp.json()

            for t in targets:
                if TARGET_URL_PATTERN in t.get("url", ""):
                    self.target = t
                    break

            if not self.target:
                print(f"No tab found matching {TARGET_URL_PATTERN}", file=sys.stderr)
                return False

            self.ws = await websockets.connect(self.target["webSocketDebuggerUrl"])
            await self._send("Runtime.enable")
            await self._send("DOM.enable")
            return True
        except Exception as e:
            print(f"CDP connect failed: {e}", file=sys.stderr)
            return False

    async def _send(self, method: str, params: Dict = None) -> Dict:
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(await self.ws.recv())
            if resp.get("id") == self._msg_id:
                if "error" in resp:
                    raise Exception(f"CDP error: {resp['error']}")
                return resp.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self._send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "userGesture": True,
        })
        if "exceptionDetails" in result:
            raise Exception(f"JS error: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    async def close(self):
        if self.ws:
            await self.ws.close()


async def scan_models() -> List[ModelInfo]:
    """Scan the ThaiAI-Pass page for available models.

    Real DOM (verified Sep 2026): the model selector is a Radix-UI modal,
    not a <select>. Open the trigger, harvest names from model cards.
    """
    cdp = CDPClient()
    if not await cdp.connect():
        return []

    # Close any open modal first
    try:
        await cdp.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key:'Escape', keyCode:27, bubbles:true}))"
        )
        await asyncio.sleep(0.4)
    except Exception:
        pass

    # Open model selector
    opened = await cdp.evaluate(
        "(()=>{const b=document.querySelector('[data-testid=\"model-selector-trigger\"]');"
        "if(b){b.click();return true;}return false;})()"
    )
    if not opened:
        await cdp.close()
        return []
    await asyncio.sleep(1.0)

    # Harvest names from cards
    raw = await cdp.evaluate("""
        JSON.stringify(Array.from(document.querySelectorAll('[data-testid="model-card"]'))
            .map(c => c.querySelector('img[alt]')?.alt)
            .filter(Boolean))
    """)

    # Close modal
    try:
        await cdp.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key:'Escape', keyCode:27, bubbles:true}))"
        )
        await asyncio.sleep(0.3)
    except Exception:
        pass

    await cdp.close()

    if not raw:
        return []

    names = json.loads(raw) if isinstance(raw, str) else raw

    discovered = []
    for idx, name in enumerate(names):
        task_classes = infer_task_classes(name, name)
        discovered.append(ModelInfo(
            id=name,
            name=name,
            task_classes=task_classes,
            priority=idx,
        ))
    return discovered


def infer_task_classes(name: str, model_id: str) -> List[str]:
    name_lower = name.lower()
    id_lower = model_id.lower()
    classes = []

    if any(k in name_lower or k in id_lower for k in ["code", "coding", "program", "dev"]):
        classes.append("code")
    if any(k in name_lower or k in id_lower for k in ["reason", "deep", "think", "opus", "sonnet"]):
        classes.append("deep-reasoning")
    if any(k in name_lower or k in id_lower for k in ["thai", "ไทย", "scb", "tllm"]):
        classes.append("thai-content")
    if any(k in name_lower or k in id_lower for k in ["fast", "flash", "haiku", "mini", "lite", "small"]):
        classes.append("fast")
    if any(k in name_lower or k in id_lower for k in ["research", "search", "pro", "max", "ultra", "opus"]):
        classes.append("research")

    if not classes:
        classes = ["code", "deep-reasoning", "thai-content", "fast", "research"]

    return classes


async def main():
    parser = argparse.ArgumentParser(description="AI-Pass Model Scanner & Cooldown Manager")
    parser.add_argument("--scan", action="store_true", help="Scan models in active tab")
    parser.add_argument("--status", action="store_true", help="Show model status & cooldowns")
    parser.add_argument("--routing", action="store_true", help="Show task-class routing map")
    parser.add_argument("--cooldown", help="Set cooldown for model ID (minutes)")
    parser.add_argument("--minutes", type=int, default=15, help="Cooldown minutes (default 15)")
    parser.add_argument("--clear", help="Clear cooldown for model ID")
    parser.add_argument("--list-targets", action="store_true", help="List CDP targets")

    args = parser.parse_args()

    mgr = ModelStatusManager(MODEL_STATUS_FILE)

    if args.list_targets:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/list") as resp:
                targets = await resp.json()
        for t in targets:
            if t.get("type") == "page":
                print(f"  {t['id']}: {t['title']} - {t['url']}")
        return

    if args.scan:
        print("Scanning models via CDP...")
        models = await scan_models()
        print(f"Discovered {len(models)} models:")
        for m in models:
            print(f"  {m.id}: {m.name} (classes: {', '.join(m.task_classes)}, priority: {m.priority})")
        mgr.update_from_scan(models)
        mgr.save()
        return

    if args.cooldown:
        mgr.set_cooldown(args.cooldown, args.minutes)
        return

    if args.clear:
        mgr.clear_cooldown(args.clear)
        return

    if args.routing:
        mgr.print_routing()
        return

    # Default: show status
    mgr.print_status()


if __name__ == "__main__":
    asyncio.run(main())