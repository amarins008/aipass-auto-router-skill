---
name: aipass-auto-router
description: "CDP bridge to ThaiAI-Pass with task routing, auto-failover."
version: 0.2.0
author: KGB008 (amarins008), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [cdp, browser-automation, llm-portal, routing, failover, thai-llm]
    related_skills: [hermes-agent, computer-use, hermes-custom-provider]
---

# AI-Pass Auto Router

A production-grade skill that bridges Hermes to an active, authenticated browser session (e.g. Brave/Chrome on `https://de.aipass.net/chat`) via Chrome DevTools Protocol (CDP). Provides task-class automated model routing, DOM injection & stream extraction, and automated failover with cooldown management.

## When to Use

- You need to use ThaiAI-Pass or similar web LLM portals without API keys
- Task requires routing to specific models by class: `code`, `deep-reasoning`, `thai-content`, `fast`, `research` — plus media classes: `image`, `video`, `music`, `audio`
- Need automated fallback when models hit rate limits or quota exhaustion
- Want to extract clean markdown from streaming responses
- Boss types `aipass: <prompt>` prefix in chat → auto-class detection picks the right class (see "Auto-class Detection" below)

**Don't use for:**
- Providers with official API keys (use `hermes-custom-provider` instead)
- Local models via Ollama (built-in Hermes support)
- Simple web scraping — use `browser_navigate`/`browser_snapshot` directly

## Auto-class Detection (chat prefix `aipass:`)

When the user types `aipass: <prompt>` or `aipass: <class> — <prompt>` in chat, route via this skill. If no class is given, detect from prompt keywords — 7 classes ordered by specificity (most specific first):

1. `video` — วิดีโอ/คลิป/video/clip/animation
2. `music` — เพลง/ดนตรี/music/song/jingle/beat/melody
3. `image` — สร้างรูป/วาด/ภาพ/draw/paint/sketch/illustration/generate.*image
4. `deep-reasoning` — พิสูจน์/ทฤษฎีบท/proof/prove/theorem/axiom/induction
5. `code` — เขียน.*code|implement|refactor|debug + python|javascript|sql|docker|recursion|OOP|regex|algorithm|api
6. `research` — สรุป.*ยาว|research|comprehensive|in.*depth|survey.*of
7. `thai-content` — แปล.*thai|translate.*thai|เขียน.*thai
8. default: `fast`

Reference: `references/auto-class-rules.md` has the exact regex set with 16/16 test cases verified.

## Prerequisites

- Chrome/Brave/Chromium/Edge with `--remote-debugging-port=9222 --user-data-dir=<custom-dir>` running
- Target portal (ThaiAI-Pass) already authenticated in that browser profile
- Python 3.11+ with `websockets`, `aiohttp`, `pydantic`
- `state/` directory writable for `model_status.json` cooldown tracking

```bash
# Install deps
pip install websockets aiohttp pydantic
```

## How to Run

### Quick Start (Windows, the path that works)

On this machine, the verified browser path is Chrome (not Brave). The fastest setup is to drop a one-click shortcut on the Desktop that launches Chrome with the correct flags and auto-opens the portal:

```bash
powershell -ExecutionPolicy Bypass -File scripts/make_desktop_shortcut.ps1
```

This writes `ThaiAI-Pass Bridge.lnk` to the user's Desktop. Double-click it → Chrome opens with `--remote-debugging-port=9222 --user-data-dir=C:\Temp\chrome-hermes` → auto-loads `https://de.aipass.net/chat`. First run: sign in once; session persists in `C:\Temp\chrome-hermes`.

After the shortcut is launched, verify the CDP endpoint:

```bash
curl http://127.0.0.1:9222/json/version
```

If `where brave` returns nothing but `where chrome` works (common on stock Windows installs), the script auto-falls-back to Chrome. Edit the constants at the top of the .ps1 if you have both, or want a different `user-data-dir`.

### Slash Commands (in-session)

```
/aipass-route <task-class> <prompt>           # Route prompt to optimal model for task class
/aipass-status                                # Show model availability & cooldowns
/aipass-scan                                  # Scan available models in current tab
/aipass-cooldown <model-id> [minutes]         # Manual cooldown (default 15)
```

### Programmatic (from scripts)

```bash
# From skill directory
python scripts/aipass_bridge.py --task-class code --prompt "Write a FastAPI auth service"
python scripts/check_models.py --scan
python scripts/check_models.py --status
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `/aipass-route <class> <prompt>` | Send prompt via optimal model for task class |
| `/aipass-status` | Show model cooldowns & availability |
| `/aipass-scan` | Discover models in active tab |
| `/aipass-cooldown <model> [min]` | Set manual cooldown |

## Procedure

### 1. Launch Browser with CDP
```bash
# Windows (Chrome — verified path on this machine)
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir=C:\Temp\chrome-hermes

# Or Brave, if installed:
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir=C:\Temp\brave-hermes

# Verify
curl http://127.0.0.1:9222/json/version
```

**First-run path discovery:** if you're not sure which Chromium-family browser is installed, run `where chrome` then `where brave` from git-bash. Whichever returns a path is the one to use — the only requirement is Chromium 136+ (or any version, with the `--user-data-dir` flag).

### 2. Open ThaiAI-Pass & Authenticate
Navigate to `https://de.aipass.net/chat` in the CDP browser and sign in (Google/Microsoft/Apple). Session persists in `--user-data-dir`.

### 3. Scan Available Models
```bash
/aipass-scan
# or
python scripts/check_models.py --scan
```
Outputs `state/model_status.json` with discovered models and capabilities.

### 4. Route a Prompt
```bash
/aipass-route code "Write a Python async HTTP client with retry logic"
```
- Parses task class (`code`)
- Selects highest-priority available model from `references/routing.md`
- Injects prompt via CDP DOM manipulation
- Streams response until generation complete
- Returns clean markdown

### 5. Check Status
```bash
/aipass-status
```
Shows each model: status (available/cooldown/error), last used, cooldown expiry.

### 6. Failover is Automatic
On rate limit / quota error toast:
1. Record 15-min cooldown in `state/model_status.json`
2. Select next model in priority list for that task class
3. Retry transparently
4. If all exhausted, return error with full cooldown map

## Pitfalls

- **Chrome 136+ requires custom `--user-data-dir`** — default profile blocks remote debugging silently. Always use a dedicated dir (e.g. `C:\Temp\brave-hermes`).
- **CDP WebSocket URL changes per tab** — bridge discovers the correct target via `/json/list` each session.
- **Model selector DOM varies** — `scripts/aipass_bridge.py` uses multiple selector strategies; update if portal UI changes.
- **Stream detection** — watches for "stop" button state + text stabilization (no new chars for 2s). May need tuning for slow models.
- **Thai content** — ensure prompt injection handles Unicode correctly; use `json.dumps(ensure_ascii=False)`.
- **No API key = no billing visibility** — cooldown is heuristic based on UI toasts, not actual quota APIs.
- **Heuristic task-class inference is imperfect** — `o1-mini` is classified as `fast` (matches `mini`), not `deep-reasoning` where it belongs. Workaround: edit `references/routing.md` with the actual model IDs from `/aipass-scan`; the bridge uses routing.md as the priority list, so explicit ordering there overrides heuristic bias.
- **Image generation has TWO stability break-paths** — when waiting for an image response, `_wait_for_response` may break via the "stable for 6s" path OR the "no stop button" fast-path. Both must call `_fetch_image_bytes` or the response will be a placeholder `[IMAGE type=… size=…]` instead of the real data URL.
- **CDP WebSocket frames cap at 1MB** — ThaiAI-Pass returns 1.2MB+ base64 JPEGs. A single `Runtime.evaluate` returning the full data URL crashes the WebSocket (`sent 1009 frame too big`). Fix: store the base64 in `window.__aipass_image_store` from the main poll loop, then read it back in 900KB chunks via `_fetch_image_bytes`. See "Image extraction" below.
- **Never regex-filter base64 data URLs** — `/logo/i.test(dataUrl)` matches random base64 substrings like `"loGOYAXuBsRF7hcaebJllyzBOSTNgr1HUM"`. Always filter on `alt` / `class` attributes, not the full src. The full src is opaque binary and any short word (`logo`, `icon`, `avatar`) WILL appear by chance in 1MB+ of base64.
- **Subprocess stdout caps near 1MB on Windows** — when verifying via `subprocess.run(text=True)`, large responses (image base64) get truncated and the test reports false FAIL. Use `Popen` + `communicate()` directly for image-class verification.
- **Multi-call verify scripts race the chat UI** — calling `bridge.route_prompt()` 6 times in quick succession (text classes × 5 + image) via separate `subprocess.run()` invocations can fail with "Modal did not appear after 3 attempts" because each subprocess reopens the page and the chat UI hasn't finished rehydrating. The verified workaround is **single-process verify**: open one `AIPassBridge()` instance, run all `route_prompt()` calls against that same bridge/connection, close at the end. See `scripts/verify_all_classes_v2.py` (preferred) vs `scripts/verify_all_classes.py` (subprocess-based, race-prone).
- **`subprocess.run(['python', ...])` uses the wrong interpreter** — when launching the bridge from a verify script, passing the literal string `'python'` resolves to whatever `python` is first on the parent's PATH (often the uv-managed system Python, which does NOT have `websockets`/`aiohttp`/`pydantic`). The bridge then exits with `Missing deps: pip install websockets aiohttp pydantic` before doing anything. Fix: pass `sys.executable` (the venv Python that already has the deps) as the first arg, or use the full path `C:\Users\KGB008\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe`. Inside a Jupyter kernel `sys.executable` is the venv Python, so use it directly.

## Chat Output Format (Boss preference)

When Boss sends `aipass: <prompt>` and the bridge returns a response, the chat reply must be **terse**: just the model name and the answer (or a media path for image/video). No procedure narration, no explanation of the route, no "PASS/FAIL" framing.

```
aipass: สวัสดี
Model: Gemini 3.1 Flash Lite
Reply: สวัสดีครับ มีอะไรให้ผมช่วยดูแลในวันนี้ไหมครับ?
```

```
aipass: สร้างรูปแมวสีชมพู
Model: Seedream 4.0
Image: 1.3 MB saved to /path/to/file.jpeg
MEDIA:<absolute path>
```

The full debug output (`[bridge] Trying: ...`, timing, fail-over log) belongs in the kernel/terminal output, not in the chat. Boss reads only the model + answer (or the image). This is a workflow preference, not just a memory item — every session that uses `aipass:` must follow it.

## Image extraction (Seedream / Seedance / Nano Banana)

When the assistant message contains an `<img>` element with a data URL, the response can be 1.2MB+ (JPEGs in `data:image/jpeg;base64,…`). Extraction flow:

1. **Poll loop** (`_wait_for_response`): return only metadata (`type`, `size`, `head[:80]`) + a storage key. The full data URL is stored in `window.__aipass_image_store` on the page side. This keeps each CDP frame under 1MB.
2. **After stability break**: call `_fetch_image_bytes(meta)` which reads `window.__aipass_image_store[key]` in 900KB chunks and reassembles the full data URL on the Python side.
3. **Both break paths must call `_fetch_image_bytes`** — the "stable for 6s" path (after `stable_count >= 12`) AND the fast-path (`not stop_btn and has_content` → `stable_count >= 3`). Forgetting either path leaves the response as a placeholder.

The `class` attribute filter must look for chrome (avatar/user-icon/logo/favicon/emoji) NOT the data URL itself — see Pitfalls above.

## Verification

1. **CDP Connection**: `curl http://127.0.0.1:9222/json/version` returns browser info
2. **Tab Discovery**: `python scripts/aipass_bridge.py --list-targets` shows ThaiAI-Pass tab
3. **Model Scan**: `/aipass-scan` outputs ≥3 models with IDs matching `routing.md`
4. **Route Test**: `/aipass-route fast "Say hello in Thai"` returns Thai response in <10s
5. **Failover Test**: Trigger rate limit (rapid requests) → observe cooldown in `/aipass-status` → next request uses fallback model
6. **Output Cleanliness**: Response is pure markdown, no UI artifacts, no partial streaming chunks
7. **Image Class Test**: `/aipass-route image "วาดรูปกบ"` returns 1.2MB+ base64 JPEG in `[IMAGE] data:image/jpeg;base64,...` form. Verify with: save response to file, `base64.b64decode()` succeeds, decoded bytes > 500KB and start with `\xff\xd8` (JPEG SOI marker). If response is `[IMAGE type=jpeg size=1416303]` placeholder, fetch path is broken (see "Image extraction" above).
8. **Auto-class detection**: run `references/auto-class-rules.md` test cases — 16/16 expected pass before declaring the heuristic ready. Boss will say "ทดสอบว่าใช้ได้จริง" — they want real bridge end-to-end, not just keyword match.