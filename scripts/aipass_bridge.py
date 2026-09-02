#!/usr/bin/env python3
"""
AI-Pass Auto Router - CDP Bridge Engine
Async WebSocket/CDP execution engine for web LLM portals.
"""

import asyncio
import json
import sys
import argparse
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import uuid

try:
    import websockets
    import aiohttp
except ImportError:
    print("Missing deps: pip install websockets aiohttp pydantic")
    sys.exit(1)

# ─── Auto-class Detection Rules ─────────────────────────────────
AUTO_CLASS_RULES = [
    (r"ภาพ.*(?:ไทย|ตัวหนังสือ)|ตัวหนังสือ.*(?:ไทย|ภาพ)|generate.*thai.*text|thai.*text.*image", "image-thai"),
    (r"สร้าง.*(?:รูป|ภาพ).*thai|วาด.*(?:ไทย|ตัวหนังสือ)|draw.*thai", "image-thai"),
    (r"วิดีโอ|คลิป|\bvideo\b|\bclip\b|animation|animated", "video"),
    (r"เพลง|ดนตรี|\bmusic\b|\bsong\b|jingle|beat|melody", "music"),
    (r"สร้าง.*รูป|วาด.*รูป|ภาพ|รูปภาพ|\bdraw\b|\bpaint\b|\bsketch\b|illustration|generate.*image|image.*of|\bdiffusion\b", "image"),
    (r"พิสูจน์|ทฤษฎีบท|\bproof\b|\bprove\b|\btheorem\b|\baxiom\b|mathematical.*proof|formal.*logic|induction|วิเคราะห์.*root.*cause|ทำไม.*(server|error|bug|fail)|root.*cause|deep.*analysis|analyze.*why", "deep-reasoning"),
    (r"เขียน.*(?:code|โค้ด|function|class|script|api|program)|เขียน(?:โปรแกรม)?|implement|refactor|debug"
     r"|\b(?:python|javascript|typescript|java|c\+\+|rust|go|ruby|php|sql|html|css|react|vue|angular|node\.?js)\b"
     r"|recursion|regex|algorithm|data structure|\bapi\b|\boop\b|\bsql\b|\borm\b|docker|kubernetes|git|linux.*command"
     r"|\bfix\b|\bdebug\b|\bpatch\b|refactor.*(code|function)|แก้บั๊ก|แก้.*โค้ด|แก้.*error|แก้.*bug",
     "code"),
    (r"สรุป.*(?:ยาว|ละเอียด|comprehensive)|\bresearch\b|วิเคราะห์.*เชิงลึก|comprehensive.*analysis|in.*depth|survey.*of", "research"),
    (r"แปล.*(?:ไทย|thai)|translate.*thai|ภาษาไทย|เขียน.*(?:บทความ|ข่าว|เนื้อหา).*ไทย", "thai-content"),
]


def auto_class(prompt: str) -> str:
    """Detect task class from prompt keywords. Falls back to 'fast'."""
    p = prompt.lower()
    for pattern, cls in AUTO_CLASS_RULES:
        if re.search(pattern, p, re.IGNORECASE):
            return cls
    return "fast"


# ─── Configuration ──────────────────────────────────────────────
CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
TARGET_URL_PATTERN = "de.aipass.net/chat"
SKILL_DIR = Path(__file__).parent.parent
STATE_DIR = SKILL_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
MODEL_STATUS_FILE = STATE_DIR / "model_status.json"
ROUTING_FILE = SKILL_DIR / "references" / "routing.md"

# ─── Data Models ────────────────────────────────────────────────


@dataclass
class ModelInfo:
    id: str
    name: str
    task_classes: List[str] = field(default_factory=list)
    priority: int = 999
    available: bool = True
    cooldown_until: Optional[str] = None
    last_used: Optional[str] = None
    error_count: int = 0


@dataclass
class CDPTarget:
    id: str
    type: str
    title: str
    url: str
    webSocketDebuggerUrl: str
    description: Optional[str] = None
    devtoolsFrontendUrl: Optional[str] = None
    faviconUrl: Optional[str] = None


@dataclass
class RouteResult:
    success: bool
    model_used: str
    response: str
    error: Optional[str] = None
    fallback_used: bool = False
    cooldown_triggered: bool = False


# ─── Model Status Manager ───────────────────────────────────────


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

    def get_available_for_class(self, task_class: str, routing: Dict[str, List[str]]) -> List[ModelInfo]:
        """Return available models for task class.

        Priority: routing.md list first, then ANY other model that has this
        task class in its inferred classes. This way if all priority models
        are on cooldown, we still have fallback candidates.
        """
        # First: explicit routing list
        explicit = []
        seen = set()
        for mid in routing.get(task_class, []):
            model = self.models.get(mid)
            if model and model.available and not model.cooldown_until:
                explicit.append(model)
                seen.add(mid)

        explicit = sorted(explicit, key=lambda m: m.priority)

        # Second: any other model that has this task class
        fallback = []
        for mid, model in self.models.items():
            if mid in seen:
                continue
            if not model.available or model.cooldown_until:
                continue
            if task_class in (model.task_classes or []):
                fallback.append(model)

        fallback = sorted(fallback, key=lambda m: (m.priority, m.id))

        return explicit + fallback

    def set_cooldown(self, model_id: str, minutes: int = 15):
        if model_id in self.models:
            m = self.models[model_id]
            m.cooldown_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
            m.available = False
            m.error_count += 1
            self.save()

    def record_use(self, model_id: str):
        if model_id in self.models:
            m = self.models[model_id]
            m.last_used = datetime.now().isoformat()
            self.save()

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


# ─── CDP Client ─────────────────────────────────────────────────


class CDPClient:
    def __init__(self, host: str = CDP_HOST, port: int = CDP_PORT):
        self.host = host
        self.port = port
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.target: Optional[CDPTarget] = None
        self._msg_id = 0

    async def connect(self) -> bool:
        """Discover and connect to the ThaiAI-Pass tab."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.host}:{self.port}/json/list") as resp:
                    targets = await resp.json()

            for t in targets:
                if TARGET_URL_PATTERN in t.get("url", ""):
                    self.target = CDPTarget(**t)
                    break

            if not self.target:
                print(f"No tab found matching {TARGET_URL_PATTERN}", file=sys.stderr)
                return False

            self.ws = await websockets.connect(self.target.webSocketDebuggerUrl)
            await self._send("Runtime.enable")
            await self._send("Page.enable")
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

    async def evaluate(self, expression: str, await_promise: bool = True) -> Any:
        result = await self._send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
            "userGesture": True,
        })
        if "exceptionDetails" in result:
            raise Exception(f"JS error: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    async def call_function(self, function_declaration: str, args: List = None) -> Any:
        """Call a function in the page context."""
        expr = f"({function_declaration})({json.dumps(args or [])})"
        return await self.evaluate(expr)

    async def close(self):
        if self.ws:
            await self.ws.close()


# ─── Bridge Engine ──────────────────────────────────────────────


class AIPassBridge:
    def __init__(self):
        self.cdp = CDPClient()
        self.status_mgr = ModelStatusManager(MODEL_STATUS_FILE)
        self.routing = self._load_routing()
        # CDP connection cache: reuse websocket across requests
        self._cdp_connected = False
        self._last_model_id: Optional[str] = None
        self._lock = asyncio.Lock()  # serialize requests to same CDP target

    async def _ensure_connection(self):
        """Re-establish CDP WebSocket connection if closed/dropped.

        Called by route_prompt() to transparently recover from
        ConnectionResetError (10054) without raising to the caller.
        Returns True if connection is usable, False if reconnect failed.
        """
        if self.cdp.ws is None or getattr(self.cdp.ws, 'closed', True):
            self._cdp_connected = False
        if not self._cdp_connected:
            try:
                self._cdp_connected = await self.cdp.connect()
            except Exception as e:
                print(f"  [bridge] reconnect failed: {type(e).__name__}: {e}", file=sys.stderr)
                self._cdp_connected = False
        return self._cdp_connected



    AUTO_CLASS_RULES = [
        (r"ภาพ.*(?:ไทย|ตัวหนังสือ)|ตัวหนังสือ.*(?:ไทย|ภาพ)|generate.*thai.*text|thai.*text.*image", "image-thai"),
        (r"สร้าง.*(?:รูป|ภาพ).*thai|วาด.*(?:ไทย|ตัวหนังสือ)|draw.*thai", "image-thai"),
        (r"วิดีโอ|คลิป|\bvideo\b|\bclip\b|animation|animated", "video"),
        (r"เพลง|ดนตรี|\bmusic\b|\bsong\b|jingle|beat|melody", "music"),
        (r"สร้าง.*รูป|วาด.*รูป|ภาพ|รูปภาพ|\bdraw\b|\bpaint\b|\bsketch\b|illustration|generate.*image|image.*of|\bdiffusion\b", "image"),
        (r"พิสูจน์|ทฤษฎีบท|\bproof\b|\bprove\b|\btheorem\b|\baxiom\b|mathematical.*proof|formal.*logic|induction|วิเคราะห์.*root.*cause|ทำไม.*(server|error|bug|fail)|root.*cause|deep.*analysis|analyze.*why", "deep-reasoning"),
        (r"เขียน.*(?:code|โค้ด|function|class|script|api|program)|เขียน(?:โปรแกรม)?|implement|refactor|debug|\b(?:python|javascript|typescript|java|c\+\+|rust|go|ruby|php|sql|html|css|react|vue|angular|node\.?js)\b|recursion|regex|algorithm|data structure|\bapi\b|\boop\b|\bsql\b|docker|kubernetes|git|linux.*command", "code"),
        (r"สรุป.*(?:ยาว|ละเอียด|comprehensive)|\bresearch\b|วิเคราะห์.*เชิงลึก|comprehensive.*analysis|in.*depth|survey.*of", "research"),
        (r"แปล.*(?:ไทย|thai)|translate.*thai|ภาษาไทย|เขียน.*(?:บทความ|ข่าว|เนื้อหา).*ไทย", "thai-content"),
    ]

    @staticmethod
    def auto_class(prompt: str) -> str:
        """Detect task class from prompt using keyword heuristic."""
        p = prompt.lower()
        for pattern, cls in AIPassBridge.AUTO_CLASS_RULES:
            if re.search(pattern, p, re.IGNORECASE):
                return cls
        return "fast"

    async def auto_route(self, prompt: str) -> "RouteResult":
        """Auto-detect class and route."""
        cls = self.auto_class(prompt)
        print(f"  [auto-route] class: {cls} prompt: {prompt[:60]}", file=sys.stderr)
        result = await self.route_prompt(cls, prompt)
        return result

    def _load_routing(self) -> Dict[str, List[str]]:
        """Parse routing.md for task-class -> model priority lists."""
        routing = {}
        if ROUTING_FILE.exists():
            content = ROUTING_FILE.read_text(encoding="utf-8")
            current_class = None
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("## "):
                    current_class = line[3:].strip().lower()
                    routing[current_class] = []
                elif line.startswith("- ") and current_class:
                    # Full model name after "- " (e.g., "Pathumma ThaiLLM 8B")
                    model_id = line[2:].strip()
                    routing[current_class].append(model_id)
        return routing

    async def list_targets(self) -> List[CDPTarget]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{self.cdp.host}:{self.cdp.port}/json/list") as resp:
                targets = await resp.json()
        return [CDPTarget(**t) for t in targets if t.get("type") == "page"]

    async def scan_models(self) -> List[ModelInfo]:
        """Scan the page for available models.

        ThaiAI-Pass uses a Radix-UI modal (NOT a <select>). The model selector
        trigger is a button; clicking it opens a modal with model cards. Each
        card has data-testid="model-card" and an <img alt="MODEL_NAME">.
        """
        if not await self.cdp.connect():
            return []

        # Close any open modal first
        await self.cdp.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key:'Escape', keyCode:27, bubbles:true}))"
        )
        await asyncio.sleep(0.4)

        # Open model selector
        opened = await self.cdp.evaluate(
            "(()=>{const b=document.querySelector('[data-testid=\"model-selector-trigger\"]');"
            "if(b){b.click();return true;}return false;})()"
        )
        if not opened:
            await self.cdp.close()
            return []
        await asyncio.sleep(1.0)

        # Harvest model names from cards
        raw = await self.cdp.evaluate("""
            JSON.stringify(Array.from(document.querySelectorAll('[data-testid="model-card"]'))
                .map(c => c.querySelector('img[alt]')?.alt)
                .filter(Boolean))
        """)

        # Close modal
        await self.cdp.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown', "
            "{key:'Escape', keyCode:27, bubbles:true}))"
        )
        await asyncio.sleep(0.3)

        await self.cdp.close()

        if not raw:
            return []

        # raw is already a JSON string (we used JSON.stringify)
        names = json.loads(raw) if isinstance(raw, str) else raw

        discovered = []
        for idx, name in enumerate(names):
            task_classes = self._infer_task_classes(name, name)
            discovered.append(ModelInfo(
                id=name,
                name=name,
                task_classes=task_classes,
                priority=idx,
            ))

        self.status_mgr.update_from_scan(discovered)
        return discovered

    def _infer_task_classes(self, name: str, model_id: str) -> List[str]:
        """Heuristic: infer task classes from model name/id."""
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

        # Default: if no specific class, add to all
        if not classes:
            classes = ["code", "deep-reasoning", "thai-content", "fast", "research"]

        return classes

    async def route_prompt(self, task_class: str, prompt: str) -> RouteResult:
        """Route prompt to best available model for task class."""
        # Reuse cached CDP connection (perf: avoid reconnect per request)
        # Use _ensure_connection() to transparently recover from connection drops
        if not await self._ensure_connection():
            return RouteResult(False, "", "", error="CDP connection failed")

        try:
            # Get available models for this task class
            # Support fixed model selection (e.g. model="gemini-3-1-flash-lite")
            routing_dict = self.routing
            if task_class not in routing_dict:
                # Use model id directly: build synthetic available list
                available = [ModelInfo(id=task_class, name=task_class, task_classes=["fast"], priority=1, available=True)]
            else:
                available = self.status_mgr.get_available_for_class(task_class, self.routing)

            if not available:
                return RouteResult(
                    False, "", "",
                    error=f"No available models for task class: {task_class}",
                    cooldown_triggered=True
                )

            # Try each model in priority order
            # Media generation takes longer — extend timeout
            self._media_timeout = 300.0 if task_class in ('music', 'image', 'video', 'audio') else 120.0

            # If first model failed but looks like a transient error (coroutine/timeout)
            # and task uses a premium model like Opus, allow one retry with lower effort
            # (keeps continuity without looping endlessly)
            retry_once = False
            for model in available:
                if retry_once:
                    retry_once = False
                    # Skip retry for already-tried first model; continue with next
                    continue
                print(f"  [bridge] Trying: {model.id}", file=sys.stderr)
                result = await self._try_model(model, prompt)
                if result.success:
                    self.status_mgr.record_use(model.id)
                    self.status_mgr.save()
                    self._last_model_id = model.id
                    return result

                # Model failed - log reason and trigger cooldown
                print(f"  [bridge] FAILED {model.id}: {result.error}", file=sys.stderr)
                self.status_mgr.set_cooldown(model.id, 15)
                self.status_mgr.save()

            return RouteResult(
                False, "", "",
                error="All models exhausted for task class",
                cooldown_triggered=True
            )

        except Exception as e:
            # Connection lost — invalidate cache so next request reconnects
            try:
                await self.cdp.close()
            except: pass
            self._cdp_connected = False
            return RouteResult(False, "", "", error=str(e))

    async def _try_model(self, model: ModelInfo, prompt: str) -> RouteResult:
        """Attempt to send prompt using specific model."""
        try:
            # 1. Select model in dropdown
            await self._select_model(model.id)

            # 2. Inject prompt
            await self._inject_prompt(prompt)

            # 3. Trigger send
            await self._trigger_send()

            # 4. Wait for response
            response = await self._wait_for_response(task_class=model.task_classes[0] if model.task_classes else 'fast', timeout=getattr(self, '_media_timeout', 120.0))

            # 5. Check for error toasts (rate limit, quota)
            if await self._check_error_toast():
                return RouteResult(False, model.id, "", error="Rate limit / quota error")

            return RouteResult(True, model.id, response)

        except Exception as e:
            return RouteResult(False, model.id, "", error=str(e))

    async def _select_model(self, model_id: str):
        """Select a model by clicking its card in the Radix-UI modal.

        Real DOM (verified Sep 2026):
        Before clicking, clear window.__aipass_image_store to prevent
        memory leak from prior image-generation runs (per Opus 5 analysis).
        """
        # Clear prior image store to prevent memory leak across runs
        try:
            await self.cdp.evaluate("if (window.__aipass_image_store) window.__aipass_image_store = {};")
        except Exception:
            pass  # non-fatal: store may not exist yet

        # 1. Click model-selector trigger
        # 2. Clear image store (done above)
        # 3. Skip if same model
        # OPTIMIZATION: Skip if same model as last request (modal already showing that model)
        if self._last_model_id == model_id:
            return  # No DOM roundtrip needed — already selected

        # Close any open modal first
        await self._close_modal()
        await asyncio.sleep(0.4)

        # Open the modal and wait for it to appear
        for attempt in range(3):
            opened = await self.cdp.evaluate(
                "(()=>{const b=document.querySelector('[data-testid=\\\"model-selector-trigger\\\"]');"
                "if(b){b.click();return true;}return false;})()"
            )
            if not opened:
                raise Exception("Model selector trigger not found")

            # Wait for modal to actually appear (poll for up to 3s)
            for _ in range(15):
                await asyncio.sleep(0.2)
                modal_visible = await self.cdp.evaluate(
                    "!!document.querySelector('[data-testid=\\\"model-selector-modal\\\"]')"
                )
                if modal_visible:
                    break
            else:
                # Modal didn't appear, retry
                if attempt < 2:
                    continue
                raise Exception("Modal did not appear after 3 attempts")

            # Now click the card
            js = f"""
            (() => {{
                const cards = Array.from(document.querySelectorAll('[data-testid="model-card"]'));
                for (const card of cards) {{
                    const img = card.querySelector('img[alt]');
                    if (img && img.alt === {json.dumps(model_id)}) {{
                        // Use pointerdown + click for Radix compatibility
                        card.dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true}}));
                        card.click();
                        return JSON.stringify({{ok: true}});
                    }}
                }}
                return JSON.stringify({{ok: false, available: cards.map(c => c.querySelector('img[alt]')?.alt).filter(Boolean)}});
            }})()
            """
            result = await self.cdp.evaluate(js)
            parsed = json.loads(result) if isinstance(result, str) else result

            if parsed.get("ok"):
                # Wait for modal to close (card click should dismiss it)
                for _ in range(10):
                    await asyncio.sleep(0.1)
                    modal_still = await self.cdp.evaluate(
                        "!!document.querySelector('[data-testid=\\\"model-selector-modal\\\"]')"
                    )
                    if not modal_still:
                        return
                # Modal stuck open, close it
                await self._close_modal()
                return

            # Card not found - check if modal was filtered (provider filter changed)
            # Reset by closing modal and retrying
            await self._close_modal()
            await asyncio.sleep(0.3)
            if attempt < 2:
                continue

            avail = parsed.get("available", [])
            raise Exception(
                f"Model '{model_id}' not found in selector. "
                f"Available: {avail[:10]}{'...' if len(avail) > 10 else ''}"
            )

    async def _close_modal(self):
        """Close any open modal via Escape key."""
        try:
            await self.cdp.evaluate("""
                (() => {
                    document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', keyCode:27, bubbles:true}));
                    document.body.click();
                })()
            """)
        except Exception:
            pass
        await asyncio.sleep(0.3)

    async def _inject_prompt(self, prompt: str):
        """Inject prompt into the chat textarea using the React-compatible setter."""
        escaped = json.dumps(prompt, ensure_ascii=False)
        js = f"""
        (() => {{
            const ta = document.querySelector('textarea');
            if (!ta) return JSON.stringify({{ok: false, reason: 'no textarea'}});
            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            setter.call(ta, {escaped});
            ta.dispatchEvent(new Event('input', {{bubbles: true}}));
            ta.dispatchEvent(new Event('change', {{bubbles: true}}));
            return JSON.stringify({{ok: true, len: ta.value.length}});
        }})()
        """
        result = await self.cdp.evaluate(js)
        parsed = json.loads(result) if isinstance(result, str) else result
        if not parsed.get("ok"):
            raise Exception(f"Inject failed: {parsed.get('reason', 'unknown')}")

    async def _trigger_send(self):
        """Click the real send button: [data-testid='send-button']."""
        js = """
        (() => {
            const btn = document.querySelector('[data-testid="send-button"]');
            if (!btn) return JSON.stringify({ok: false, reason: 'no send button'});
            if (btn.disabled) return JSON.stringify({ok: false, reason: 'disabled'});
            btn.click();
            return JSON.stringify({ok: true});
        })()
        """
        result = await self.cdp.evaluate(js)
        parsed = json.loads(result) if isinstance(result, str) else result
        if not parsed.get("ok"):
            raise Exception(f"Send failed: {parsed.get('reason', 'unknown')}")

    async def _wait_for_response(self, task_class: str = 'fast', timeout: float = 120.0) -> str:
        """Wait for the assistant response to stabilize and return only the new response."""
        start = time.time()
        last_text = ""
        stable_count = 0

        # Record the current last assistant message count before sending.
        # ThaiAI-Pass uses [data-role="assistant"] (verified Sep 2026).
        # Fall back to common ChatGPT-style selectors.
        before_expr = """
        (() => {
            const sels = [
                'main [data-role="assistant"]',
                '[data-message-author-role="assistant"]',
                'article[data-role="assistant"]',
                '[data-testid="message-assistant"]',
            ];
            for (const sel of sels) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) return els.length;
            }
            return 0;
        })()
        """
        before_count = await self.cdp.evaluate(before_expr)
        before_count = int(before_count) if before_count else 0

        # Pick the most reliable selector for messages (ThaiAI-Pass first)
        message_selectors = [
            'main [data-role="assistant"]',
            '[data-message-author-role="assistant"]',
            'article[data-role="assistant"]',
            '[data-testid="message-assistant"]',
        ]

        # Cap the return payload at < 1MB to avoid CDP WebSocket frame limit
        # (1MB). Real base64 images are 1.2MB+ — store them in window storage
        # and return only the storage key + metadata. Python reads the bytes
        # back via a small follow-up call.
        while time.time() - start < timeout:
            elapsed = time.time() - start
            # Hang detection: 80% of timeout with no content received -> break early
            # (Opus 5 / long-context models can hang; don't waste 120s of timeout)
            if elapsed > (timeout * 0.8) and not last_text:
                print(f"  [bridge] _wait_for_response: 80% timeout reached with no content (elapsed={elapsed:.1f}s), breaking", file=sys.stderr)
                break
            try:
                # Find the last assistant message and extract content
                # (text AND images, so image-generation models return URLs).
                expr = f"""
                (() => {{
                    let msgs = [];
                    for (const sel of {json.dumps(message_selectors)}) {{
                        msgs = Array.from(document.querySelectorAll(sel));
                        if (msgs.length > 0) break;
                    }}
                    if (msgs.length <= {before_count}) return JSON.stringify({{text: '', images: [], stable: true}});
                    const last = msgs[msgs.length - 1];

                    // Collect image URLs (img src, srcset, data URLs).
                    // IMPORTANT: image may not have rendered yet, so naturalWidth
                    // is 0 — use src length as fallback filter to skip tiny icons.
                    // BUG: regex /logo/ etc. accidentally matches random base64
                    // substrings inside the data URL (e.g. "loGOYAXuBsRF7...").
                    // Fix: only inspect the alt / class / filename, not the full src.
                    const images = [];
                    last.querySelectorAll('img').forEach(img => {{
                        const alt = (img.getAttribute('alt') || '').toLowerCase();
                        const cls = (img.getAttribute('class') || '').toLowerCase();
                        // Skip obvious UI chrome: avatars/icons/logos. Use exact
                        // substring match on alt/class — NOT on the data URL itself.
                        if (/avatar|user-?icon|logo|favicon|emoji/.test(alt)) return;
                        if (/avatar|user-?icon|logo|favicon|emoji/.test(cls)) return;
                        const src = img.src || img.getAttribute('src') || '';
                        const srcset = img.getAttribute('srcset') || '';
                        // Skip data URLs that are too small to be a real image (< 5KB)
                        if (src.startsWith('data:image/') && src.length < 5000) return;
                        if (src) images.push(src);
                        else if (srcset) images.push(srcset.split(',')[0].trim().split(' ')[0]);
                    }});

                    // Target the markdown content container to avoid action buttons.
                    const md = last.querySelector('.markdown-content') || last;

                    function extractText(el) {{
                        if (!el) return '';
                        const tag = el.tagName || '';
                        if (['BUTTON', 'SVG', 'SCRIPT', 'STYLE', 'NOSCRIPT'].includes(tag)) return '';
                        let text = '';
                        for (const node of el.childNodes) {{
                            if (node.nodeType === 3) {{
                                text += node.textContent;
                            }} else if (node.nodeType === 1) {{
                                text += extractText(node);
                            }}
                        }}
                        return text;
                    }}
                    const raw = extractText(md);
                    const text = raw.replace(/[ \\t]+/g, ' ').replace(/\\n{{3,}}/g, '\\n\\n').trim();

                    // Collect audio/video URLs (mp3, wav, mp4, webm).
                    const audioUrls = [];
                    last.querySelectorAll('audio[src], video[src]').forEach(el => {{
                        const src = el.src || el.getAttribute('src') || '';
                        if (src && !src.startsWith('blob:')) audioUrls.push(src);
                    }});

                    // Store large base64 images in window storage, return only
                    // short metadata (data URL length, type, head bytes).
                    if (!window.__aipass_image_store) window.__aipass_image_store = {{}};
                    const meta = images.map((src, i) => {{
                        const key = `img_{{$before_count}}_{{i}}_{{Date.now()}}`;
                        window.__aipass_image_store[key] = src;
                        // Return at most 100 chars of head + size to keep payload small.
                        return {{
                            key,
                            type: (src.match(/^data:image\\/(\\w+);/) || [])[1] || 'png',
                            size: src.length,
                            head: src.substring(0, 80)
                        }};
                    }});

                    return JSON.stringify({{text, images: meta, audioUrls}});
                }})()
                """
                import json as _json
                payload_raw = await self.cdp.evaluate(expr)
                try:
                    payload = _json.loads(payload_raw) if payload_raw else {{"text": "", "images": []}}
                except Exception:
                    payload = {{"text": str(payload_raw), "images": []}}
                text = payload.get("text", "") or ""
                images = payload.get("images", []) or []
                audio_urls = payload.get("audioUrls", []) or []
                _elapsed = int(time.time() - start)
                print(f"  [wait] t={_elapsed}s text_len={len(text)} imgs={len(images)} audios={len(audio_urls)} stable={stable_count}", file=sys.stderr)

                # Ignore common "loading" placeholders - the real text will follow.
                loading_phrases = (
                    'กำลังประมวลผล กรุณารอสักครู่', 'กำลังสร้างเพลง กรุณารอสักครู่',
                    'กำลังสร้างรูปภาพ กรุณารอสักครู่', 'กำลังสร้างวิดีโอ กรุณารอสักครู่',
                    'Loading...', 'กำลัง加载...', '...',
                )
                if text and any(p in text for p in loading_phrases):
                    text = ''

                audio_urls = payload.get("audioUrls", []) or []

                # Only treat as content if there's real text OR audio is present.
                # Placeholder images (waveform thumbnails) appear before audio
                # is ready — don't break early on those alone.
                has_text = bool(text)
                has_audio = bool(audio_urls)
                has_content = has_text or has_audio

                if has_content:
                    composed = text
                    # Only include image placeholders if there's actual text
                    # (images without text = loading placeholder for media gen)
                    if images and has_text:
                        for img in images:
                            tag = f"[IMAGE type={img.get('type', 'png')} size={img.get('size', 0)}]"
                            composed = (composed + "\n\n" if composed else "") + tag
                    if audio_urls:
                        for url in audio_urls:
                            composed = (composed + "\n\n" if composed else "") + f"[AUDIO] {url}"
                    if composed != last_text:
                        last_text = composed
                        stable_count = 0
                    else:
                        stable_count += 1
                        if stable_count >= 12:  # stable for ~6s
                            real_urls = await self._fetch_image_bytes(images)
                            final = text
                            if real_urls:
                                final = (text + "\n\n" if text else "") + "\n".join(f"[IMAGE] {u}" for u in real_urls)
                            if audio_urls:
                                final = (final + "\n\n" if final else "") + "\n".join(f"[AUDIO] {u}" for u in audio_urls)
                            last_text = final
                            break
                else:
                    stable_count = 0

                # Also check if stop button exists (still generating)
                stop_btn = await self.cdp.evaluate("""
                    !!document.querySelector('[data-testid="stop-button"]') ||
                    Array.from(document.querySelectorAll('button')).some(b =>
                        /stop generating|หยุด|กำลังสร้าง/i.test(b.textContent || '')
                    )
                """)
                if not stop_btn and has_content:
                    stable_count += 1
                    # Media generation (music/image/video) takes longer;
                    # require higher stability before breaking.
                    # For music: wait for audio element to appear, not just placeholder images.
                    min_stable = 18 if task_class in ('music', 'image', 'video', 'audio') else 3
                    if stable_count >= min_stable and (has_text or has_audio):
                        real_urls = await self._fetch_image_bytes(images)
                        final = text
                        if real_urls:
                            final = (text + "\n\n" if text else "") + "\n".join(f"[IMAGE] {u}" for u in real_urls)
                        if audio_urls:
                            final = (final + "\n\n" if final else "") + "\n".join(f"[AUDIO] {u}" for u in audio_urls)
                        last_text = final
                        break

                await asyncio.sleep(0.5)
            except Exception:
                await asyncio.sleep(0.5)

        return last_text.strip()

    async def _fetch_image_bytes(self, image_meta: list) -> list:
        """Fetch full base64 data URLs from window.__aipass_image_store.

        CDP WebSocket frames are capped at 1MB, so a 1.2MB data URL cannot
        be returned in a single evaluate() round-trip. We instead chunk
        the read on the JS side and reassemble in Python.
        """
        if not image_meta:
            return []
        urls = []
        for meta in image_meta:
            key = meta.get("key")
            if not key:
                continue
            try:
                size = meta.get("size", 0)
                if size == 0:
                    urls.append("")
                    continue
                # Read in 900KB chunks so each CDP frame stays well below 1MB.
                chunk_size = 900_000
                num_chunks = (size + chunk_size - 1) // chunk_size
                parts = []
                for i in range(num_chunks):
                    start = i * chunk_size
                    end = min(start + chunk_size, size)
                    expr = f"""
                    (() => {{
                        const data = (window.__aipass_image_store || {{}})["{key}"];
                        if (!data) return '';
                        return data.substring({start}, {end});
                    }})()
                    """
                    part = await self.cdp.evaluate(expr)
                    if isinstance(part, dict):
                        part = (part.get("result") or {{}}).get("value", "")
                    if not part:
                        break
                    parts.append(part)
                full = "".join(parts)
                if full.startswith("data:image/"):
                    urls.append(full)
                else:
                    urls.append(f"[image-incomplete size={size} got={len(full)}]")
            except Exception as e:
                urls.append(f"[image-fetch-failed key={key} err={type(e).__name__}]")
        return urls

    async def _check_error_toast(self) -> bool:
        """Check for rate limit / quota error toasts."""
        try:
            expr = """
            const toasts = document.querySelectorAll('[role="alert"], .toast, .notification, [data-testid="toast"]');
            for (const t of toasts) {
                const text = (t.innerText || t.textContent || '').toLowerCase();
                if (text.includes('rate limit') || text.includes('quota') || text.includes('exceeded') || text.includes('too many') || text.includes('429')) {
                    return true;
                }
            }
            return false;
            """
            return await self.cdp.evaluate(expr)
        except Exception:
            return False


# ─── CLI ────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="AI-Pass Auto Router Bridge")
    ALL_CLASSES = ["code", "deep-reasoning", "thai-content", "fast", "research", "image", "video", "music", "audio"]
    parser.add_argument("--task-class", choices=ALL_CLASSES, help="Task class for routing")
    parser.add_argument("--prompt", help="Prompt to send")
    parser.add_argument("--list-targets", action="store_true", help="List available CDP targets")
    parser.add_argument("--scan", action="store_true", help="Scan models in active tab")
    parser.add_argument("--status", action="store_true", help="Show model cooldown & availability status")
    parser.add_argument("--clear-cooldown", action="store_true", help="Clear all cooldowns")
    parser.add_argument("--set-cooldown", nargs=2, metavar=("MODEL", "MINUTES"), help="Set cooldown for a model (default 15 min)")

    args = parser.parse_args()

    bridge = AIPassBridge()

    if args.list_targets:
        targets = await bridge.list_targets()
        for t in targets:
            print(f"  {t.id}: {t.title} - {t.url}")
        return

    if args.scan:
        models = await bridge.scan_models()
        print(f"Discovered {len(models)} models:")
        for m in models:
            print(f"  {m.id}: {m.name} (classes: {', '.join(m.task_classes)}, priority: {m.priority})")
        return

    if args.status:
        print("Model Status:")
        print("=" * 60)
        for mid, m in sorted(bridge.status_mgr.models.items()):
            status = "available" if m.available and not m.cooldown_until else "cooldown"
            cd = f"  until {m.cooldown_until}" if m.cooldown_until else ""
            print(f"  {mid:30s}  {status}{cd}")
        return

    if args.clear_cooldown:
        for m in bridge.status_mgr.models.values():
            m.cooldown_until = None
            m.available = True
            m.error_count = 0
        bridge.status_mgr.save()
        print("All cooldowns cleared.")
        return

    if args.set_cooldown:
        model_id, minutes = args.set_cooldown
        bridge.status_mgr.set_cooldown(model_id, int(minutes))
        print(f"Cooldown set for '{model_id}': {minutes} minutes")
        return

    if args.task_class and args.prompt:
        result = await bridge.route_prompt(args.task_class, args.prompt)
        if result.success:
            print(result.response)
        else:
            print(f"ERROR: {result.error}", file=sys.stderr)
            if result.cooldown_triggered:
                print("Cooldowns active. Check --status", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())