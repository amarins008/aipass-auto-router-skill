"""
Ad-hoc verification v2 for aipass-auto-router (post image-class fix).
Single-process: opens one bridge, runs all checks via direct method calls.
"""
import asyncio
import base64
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
BRIDGE_SCRIPT = SKILL_DIR / "scripts" / "aipass_bridge.py"
STATE = SKILL_DIR / "state" / "model_status.json"

sys.path.insert(0, str(BRIDGE_SCRIPT.parent))
from aipass_bridge import AIPassBridge, auto_class, AUTO_CLASS_RULES

LOADING = ("กำลังประมวลผล กรุณารอสักครู่", "Loading...", "กำลังโหลด...", "...")


def clear_cooldowns():
    d = json.loads(STATE.read_text(encoding="utf-8"))
    for v in d.values():
        v["cooldown_until"] = None
        v["available"] = True
        v["error_count"] = 0
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def cooldown_models(names):
    d = json.loads(STATE.read_text(encoding="utf-8"))
    until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    for m in names:
        if m in d:
            d[m]["cooldown_until"] = until
            d[m]["available"] = False
            d[m]["error_count"] = 1
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> int:
    print("=" * 60)
    print("aipass-auto-router v2 verification (single-process)")
    print("=" * 60)
    results = []

    # ── 1. auto-class detection (16 cases) ─────────────────────
    print("\n[1] auto-class detection (16 cases)")
    auto_cases = [
        ("สวัสดีตอนเช้า", "fast"),
        ("เขียน Python function คำนวณ fibonacci", "code"),
        ("สร้างรูปแมวสีชมพู", "image"),
        ("พิสูจน์ว่า 2+2=4 แบบ Peano axioms", "deep-reasoning"),
        ("สรุป quantum computing แบบยาวๆ", "research"),
        ("อธิบาย recursion", "code"),
        ("แปล Hello เป็นไทย", "thai-content"),
        ("เพลงบรรเลง", "music"),
        ("วิดีโอแมวเล่นน้ำ", "video"),
        ("write a Python function", "code"),
        ("draw a cat", "image"),
        ("prove this theorem", "deep-reasoning"),
        ("refactor this javascript", "code"),
        ("explain docker", "code"),
        ("ทำ SQL query", "code"),
        ("อธิบาย transformer architecture แบบสั้น", "fast"),
    ]
    auto_pass = sum(1 for p, exp in auto_cases if auto_class(p) == exp)
    print(f"  {auto_pass}/{len(auto_cases)} pass")
    results.append(("auto-class", auto_pass == len(auto_cases)))

    # ── 2-4. bridge end-to-end via single connection ────────────
    clear_cooldowns()
    bridge = AIPassBridge()
    if not await bridge.cdp.connect():
        print("CDP connect failed")
        return 1

    # [2] text classes
    print("\n[2] bridge end-to-end (5 text classes)")
    text_cases = [
        ("fast",          "1+1 เท่ากับอะไร",                "2"),
        ("thai-content",  "แปล Hello เป็นไทย",            "สวัสดี"),
        ("code",          "เขียน Python hello world",       "print"),
        ("deep-reasoning","อธิบาย recursion สั้นๆ",         "recursion"),
        ("research",      "สรุป AI แบบสั้น 2 บรรทัด",     "AI"),
    ]
    text_pass = 0
    for tc, prompt, expected in text_cases:
        clear_cooldowns()
        print(f"  [{tc}] ...", end=" ", flush=True)
        try:
            r = await bridge.route_prompt(tc, prompt)
            passed = r.success and expected.lower() in r.response.lower()
        except Exception as e:
            r = None
            passed = False
            print(f"exc={type(e).__name__} ", end="")
        text_pass += int(passed)
        print("PASS" if passed else f"FAIL (model={r.model_used if r else '-'}, len={len(r.response) if r else 0})")
    results.append(("bridge-text-5", text_pass == len(text_cases)))
    print(f"  text: {text_pass}/{len(text_cases)} pass")

    # [3] image class
    print("\n[3] image class")
    clear_cooldowns()
    print("  [image] ...", end=" ", flush=True)
    try:
        r = await bridge.route_prompt("image", "วาดรูปผีเสื้อ")
        has_image = r.success and "[IMAGE]" in r.response and "data:image" in r.response
        # Decode and save
        if has_image:
            m = re.search(r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)", r.response)
            if m:
                ext, b64 = m.group(1), m.group(2)
                raw = base64.b64decode(b64)
                import tempfile
                out = Path(tempfile.gettempdir()) / f"hermes-verify-butterfly.{ext}"
                out.write_bytes(raw)
                print(f"PASS ({len(raw)/1024:.1f} KB {ext}, saved {out.name})")
            else:
                print("FAIL (data URL malformed)")
                has_image = False
        else:
            print(f"FAIL (success={r.success}, len={len(r.response)})")
    except Exception as e:
        print(f"FAIL (exc={type(e).__name__})")
        has_image = False
    results.append(("image-class", has_image))

    # [4] auto-failover
    print("\n[4] auto-failover (top-3 deep-reasoning models cooled)")
    clear_cooldowns()
    cooldown_models(["Claude Sonnet 5", "Claude Opus 5", "o3 Deep Research"])
    print("  [failover] ...", end=" ", flush=True)
    try:
        r = await bridge.route_prompt("deep-reasoning", "ใครคือ Einstein")
        failover_ok = r.success and "einstein" in r.response.lower()
    except Exception as e:
        failover_ok = False
        print(f"exc={type(e).__name__} ", end="")
    print("PASS" if failover_ok else "FAIL")
    results.append(("auto-failover", failover_ok))

    await bridge.cdp.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, ok in results:
        print(f"  {name:20s} : {'PASS' if ok else 'FAIL'}")
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} test groups passed")
    clear_cooldowns()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
