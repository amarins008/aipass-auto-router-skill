"""
End-to-end verification for aipass_bridge.py.

Tests all 5 task classes plus auto-failover by clearing cooldowns before
each test, then by simulating failure of top-priority models.

Usage:
    python scripts/verify.py
"""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRIDGE = Path(__file__).parent / "aipass_bridge.py"
STATE = Path(__file__).parent.parent / "state" / "model_status.json"

# Tests: (task_class, prompt, expected_substring)
TESTS = [
    ("fast",          "1+1 เท่ากับอะไร",                "2"),
    ("thai-content",  "แปล Hello เป็นไทย",            "สวัสดี"),
    ("code",          "เขียน Python hello world",       "print"),
    ("deep-reasoning","อธิบาย recursion สั้นๆ",         "recursion"),
    ("research",      "สรุป AI แบบสั้น 2 บรรทัด",     "AI"),
]

LOADING_TEXTS = ("กำลังประมวลผล กรุณารอสักครู่", "Loading...", "กำลังโหลด...", "...")


def clear_cooldowns() -> None:
    d = json.loads(STATE.read_text(encoding="utf-8"))
    for v in d.values():
        v["cooldown_until"] = None
        v["available"] = True
        v["error_count"] = 0
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def cooldown_models(model_names) -> None:
    d = json.loads(STATE.read_text(encoding="utf-8"))
    until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    for m in model_names:
        if m in d:
            d[m]["cooldown_until"] = until
            d[m]["available"] = False
            d[m]["error_count"] = 1
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def run_bridge(task_class: str, prompt: str, timeout: int = 90) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(BRIDGE), "--task-class", task_class, "--prompt", prompt],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(BRIDGE.parent.parent),
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode == 0 and out and out not in LOADING_TEXTS:
        return True, out
    return False, f"rc={result.returncode} | out={out[:200]!r} | err={err[:200]!r}"


async def main() -> int:
    print("=" * 60)
    print("aipass_bridge.py end-to-end verification")
    print("=" * 60)

    results = []
    # Test 1: All 5 task classes in clean state
    for task_class, prompt, expected in TESTS:
        clear_cooldowns()
        print(f"\n[{task_class}] prompt={prompt!r}")
        ok, resp = await asyncio.to_thread(run_bridge, task_class, prompt)
        passed = ok and expected.lower() in resp.lower()
        print(f"  -> {'PASS' if passed else 'FAIL'}")
        print(f"  response: {resp[:200]}")
        results.append((task_class, passed))

    # Test 2: Auto-failover — cooldown top-3 deep-reasoning models
    print("\n[failover] cooldown Claude Sonnet 5 + Claude Opus 5 + o3 Deep Research")
    clear_cooldowns()
    cooldown_models(["Claude Sonnet 5", "Claude Opus 5", "o3 Deep Research"])
    ok, resp = await asyncio.to_thread(run_bridge, "deep-reasoning", "ใครคือ Einstein")
    failover_ok = ok and "einstein" in resp.lower()
    print(f"  -> {'PASS' if failover_ok else 'FAIL'}")
    print(f"  response: {resp[:200]}")
    results.append(("failover", failover_ok))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for tc, ok in results:
        print(f"  {tc:18s} : {'PASS' if ok else 'FAIL'}")
    print(f"\n{passed}/{len(results)} tests passed")
    clear_cooldowns()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
