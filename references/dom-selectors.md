# ThaiAI-Pass DOM Reference (verified Sep 2026)

Empirically verified selectors and patterns. Use these, not the placeholder strategies in SKILL.md — those were written before we had a live CDP probe and have been superseded by the bugs/fixes below.

## Selectors that actually work

| Element | Selector | Notes |
|---|---|---|
| Model selector trigger | `[data-testid="model-selector-trigger"]` | A `<button>` showing the current model name as its text. |
| Model selector modal | `[data-testid="model-selector-modal"]` | Radix-UI dialog, NOT a `<select>`. Class names are Radix-generated and unstable — use the testid. |
| Model card | `[data-testid="model-card"]` | `role="button"`, `tabindex="0"`. 32 cards in the modal as of this writing. |
| Model name in card | `img[alt="<EXACT_NAME>"]` | Each card has a model icon `<img>` with the model name as `alt`. Match exactly — spaces, casing, "(Preview)" suffix all matter. |
| Send button | `[data-testid="send-button"]` | Disabled when textarea is empty. |
| Stop button (while streaming) | `[data-testid="stop-button"]` OR any button matching `/stop generating\|หยุด/i` | |
| Assistant message | `main [data-role="assistant"]` | Both user and assistant messages have `data-role`. Scope to `main` to avoid sidebar history. Do NOT use `data-message-author-role="assistant"` — that is ChatGPT-style and ThaiAI-Pass does not emit it. |
| Response text | `.markdown-content` inside the assistant message | Sibling of the action bar (Copy/Like/Dislike/Refresh). Targeting this avoids extracting the button text. |

## Model inventory (Sep 2026)

The 32 models as of this writing. Use these **exact** names with the bridge — they appear in `img.alt` and in the trigger button text.

- Gemini 3.1 Flash Lite, Gemini 3.7 Flash, Gemini 3.1 Pro (Preview)
- Claude Sonnet 5, Claude Opus 5
- GPT-5.6 Terra, GPT-5.6 Sol
- o3 Deep Research
- DeepSeek V3.2, Grok 4.3, Qwen3-Next, GLM 5.2, Kimi K2.7 Code
- Sonar, Sonar Reasoning Pro, Sonar Deep Research
- Llama 4 Maverick, Llama 4 Scout
- MiniMax M2, Mistral Large 3, Mistral Medium 3
- Pathumma ThaiLLM 8B
- Seedream 4.0, Seedream 5.0 Lite
- Seedance 2.0 Mini, Seedance 2.0 Fast, Seedance 2.0
- Nano Banana, Nano Banana Pro
- Veo 3.1 Fast
- Lyria 3 Clip, Lyria 3 Pro

Re-discover with: `python scripts/check_models.py --scan`

## Response extraction (working pattern)

```javascript
const msgs = document.querySelectorAll('main [data-role="assistant"]');
const last = msgs[msgs.length - 1];
const md = last.querySelector('.markdown-content') || last;

function extractText(el) {
  if (!el) return '';
  const tag = el.tagName || '';
  if (['BUTTON', 'SVG', 'SCRIPT', 'STYLE', 'NOSCRIPT'].includes(tag)) return '';
  let text = '';
  for (const node of el.childNodes) {
    if (node.nodeType === 3) text += node.textContent;
    else if (node.nodeType === 1) text += extractText(node);
  }
  return text;
}
const raw = extractText(md);
return raw.replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
```

## Bugs we hit and how we fixed them

1. **`:has-text()` is not CSS** — Playwright-only pseudo-class, browser DOM throws `SyntaxError`. Use `Array.from(querySelectorAll('button')).some(b => /pattern/i.test(b.textContent))` instead.

2. **Bare multi-class CSS breaks `querySelectorAll`** — strings like `'div.group.flex.gap-4...'` get passed as a single class and throw. Always use `[data-testid="..."]` or scope with `main` / `aside` first.

3. **Radix cards need `pointerdown` + `click`** — single `card.click()` sometimes does not fire Radix's selection. Dispatch `new PointerEvent('pointerdown', {bubbles: true})` first, then `click()`.

4. **Modal close requires DOM-removal polling, not just `Escape` keydown** — Radix does animate-out. Poll for the modal element to be gone (up to 3s) before treating it as closed.

5. **Loading placeholder looks like a real response** — `กำลังประมวลผล กรุณารอสักครู่` (and `Loading...`, `กำลังโหลด...`, `...`) is the streaming-placeholder text. Filter it out before the "text stable" check or you'll return an empty placeholder as the answer.

6. **Response text is contaminated by the action bar** — without targeting `.markdown-content`, the extraction includes "Copy messageLikeDislikeRefresh" because the action buttons sit inside the same `data-role` wrapper.

7. **`el.className` is `SVGAnimatedString` on `<svg>` elements** — calling `.substring()` on it throws. Guard with `typeof c === 'string'` checks or use `el.getAttribute('class')`.

8. **Python `__pycache__` hides edits** — `scripts/__pycache__/aipass_bridge.cpython-311.pyc` will keep the old bytecode even after you `write_file` the source. If a test "still fails the same way" after a fix, `rm -rf scripts/__pycache__` first.

9. **`get_available_for_class` used to only return the explicit routing.md list** — when the 6-8 priority models all cooldowned, the bridge gave up even though other models with the right `task_classes` were available. Fixed by appending a fallback list of any other available model with the class.

10. **DOMException in `Runtime.evaluate` returns `result.result.value === null` and silently kills the rest of the expression** — the `if (parsed.get("ok"))` path in `_select_model` was sometimes reading from a stale or null result, leading to mysterious "Available: []" even when cards were visible. We now wrap modal-related JS in try/catch in the CDP layer and the `evaluate()` helper raises on `exceptionDetails`.

## Cooldown management

- 15-min default cooldown, stored in `state/model_status.json` per model.
- Clear all cooldowns manually before a test run:

```python
import json
from pathlib import Path
p = Path(r"C:\Users\KGB008\AppData\Local\hermes\skills\autonomous-ai-agents\aipass-auto-router\state\model_status.json")
d = json.loads(p.read_text(encoding="utf-8"))
for v in d.values():
    v["cooldown_until"] = None
    v["available"] = True
    v["error_count"] = 0
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
```

- `_expire_cooldowns()` runs on every load/save and clears models whose `cooldown_until` is in the past, so 15 minutes after the last failure they auto-recover.

## Verification

Run the included end-to-end script: `python scripts/verify_all_classes.py`. It clears cooldowns between tests and validates all 5 task classes return real responses.
