---
name: aipass-auto-router
description: "CDP bridge to ThaiAI-Pass with task routing, auto-failover."
version: 0.1.2
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
- Task requires routing to specific models by class: `code`, `deep-reasoning`, `thai-content`, `fast`, `research`
- Need automated fallback when models hit rate limits or quota exhaustion
- Want to extract clean markdown from streaming responses

**Don't use for:**
- Providers with official API keys (use `hermes-custom-provider` instead)
- Local models via Ollama (built-in Hermes support)
- Simple web scraping — use `browser_navigate`/`browser_snapshot` directly

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

## Verification

1. **CDP Connection**: `curl http://127.0.0.1:9222/json/version` returns browser info
2. **Tab Discovery**: `python scripts/aipass_bridge.py --list-targets` shows ThaiAI-Pass tab
3. **Model Scan**: `/aipass-scan` outputs ≥3 models with IDs matching `routing.md`
4. **Route Test**: `/aipass-route fast "Say hello in Thai"` returns Thai response in <10s
5. **Failover Test**: Trigger rate limit (rapid requests) → observe cooldown in `/aipass-status` → next request uses fallback model
6. **Output Cleanliness**: Response is pure markdown, no UI artifacts, no partial streaming chunks