"""
End-to-end verification for aipass_bridge.py.

Tests all 5 task classes against the live ThaiAI-Pass tab, with cooldown
reset between tests. Exits 0 if all pass, 1 otherwise. Prints a summary.

Usage:
    python scripts/verify_all_classes.py
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

BRIDGE = Path(__file__).parent / "aipass_bridge.py"
STATE = Path(__file__).parent.parent / "state" / "model_status.json"

# (task_class, prompt, expected_substring)
TESTS = [
    ("fast",          "1+1 เท่ากับอะไร",         "2"),
    ("thai-content",  "แปล Hello เป็นไทย",      "สวัสดี"),
    ("code",          "เขียน Python hello",     "print"),
    ("deep-reasoning", "อธิบาย recursion สั้นๆ", "recursion"),
    ("research",      "สรุป AI แบบสั้น 2 บรรทัด", "AI"),
]

LOADING_TEXTS = (
    "กำลังประมวลผล กรุณารอสักครู่",
    "Loading...",
    "กำลังโหลด...",
    "...",
)


def clear_cooldowns() -> None:
    """Reset all cooldowns so each test starts from a clean slate."""
    d = json.loads(STATE.read_text(encoding="utf-8"))
    for v in d.values():
        v["cooldown_until"] = None
        v["available"] = True
        v["error_count"] = 0
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def run_bridge(task_class: str, prompt: str, timeout: int = 90) -> tuple[bool, str]:
    """Invoke aipass_bridge.py and return (success, response_or_error)."""
    result = subprocess.run(
        [sys.executable, str(BRIDGE), "--task-class", task_class, "--prompt", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
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
    for task_class, prompt, expected in TESTS:
        clear_cooldowns()
        print(f"\n[{task_class}] prompt={prompt!r}")
        ok, resp = await asyncio.to_thread(run_bridge, task_class, prompt)
        is_loading = resp in LOADING_TEXTS
        has_expected = expected.lower() in resp.lower() if expected else True
        passed = ok and not is_loading and has_expected
        status = "PASS" if passed else "FAIL"
        print(f"  -> {status}")
        print(f"  response: {resp[:200]}")
        if not passed and expected and not is_loading:
            print(f"  expected substring: {expected!r}")
        results.append((task_class, passed, resp[:200]))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    for tc, ok, _ in results:
        print(f"  {tc:18s} : {'PASS' if ok else 'FAIL'}")
    print(f"\n{passed}/{len(results)} task classes passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
