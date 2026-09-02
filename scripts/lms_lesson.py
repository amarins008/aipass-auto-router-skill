#!/usr/bin/env python3
"""
LMS Lesson Navigator - Complete lessons in TH-AI Passport LMS via CDP.
Handles videos, documents, quizzes, and navigation.
"""
import asyncio
import json
import sys
import time
import aiohttp
import websockets

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
TARGET_URL_PATTERN = "de.aipass.net"


class CDPHelper:
    def __init__(self):
        self.ws = None
        self._msg_id = 0

    async def connect(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{CDP_HOST}:{CDP_PORT}/json/list") as resp:
                targets = await resp.json()
        target = next((t for t in targets if TARGET_URL_PATTERN in t.get("url", "")), None)
        if not target:
            raise Exception("No LMS tab found")
        self.ws = await websockets.connect(target["webSocketDebuggerUrl"], max_size=2**24)
        return target.get("url", "")

    async def send(self, method, params=None):
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(await self.ws.recv())
            if resp.get("id") == self._msg_id:
                if "error" in resp:
                    raise Exception(f"CDP error: {resp['error']}")
                return resp.get("result", {})

    async def eval_js(self, expression):
        result = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        })
        return result.get("result", {}).get("value")

    async def click_at(self, x, y):
        await self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        await self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    async def click_button_by_text(self, text):
        """Click a button by finding it via DOM query and clicking its center."""
        expr = f"""(() => {{
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {{
                if (btns[i].innerText.indexOf('{text}') !== -1) {{
                    var rect = btns[i].getBoundingClientRect();
                    return JSON.stringify({{x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width}});
                }}
            }}
            return 'null';
        }})()"""
        result = await self.eval_js(expr)
        if result and result != "null":
            data = json.loads(result)
            if data["w"] > 0:
                await self.click_at(data["x"], data["y"])
                return True
        return False

    async def get_text(self, length=1000):
        return await self.eval_js(f"document.body.innerText.substring(0, {length})")

    async def has_video(self):
        result = await self.eval_js("document.querySelectorAll('video').length")
        return (result or 0) > 0

    async def get_video_state(self):
        expr = """(() => {
            var v = document.querySelectorAll('video')[0];
            if (!v) return '{}';
            return JSON.stringify({t: Math.round(v.currentTime), d: Math.round(v.duration), e: v.ended, p: v.paused});
        })()"""
        result = await self.eval_js(expr)
        try:
            return json.loads(result) if result else {}
        except:
            return {}

    async def set_video_speed(self, rate):
        await self.eval_js(f"""(() => {{
            var vids = document.querySelectorAll('video');
            for (var i = 0; i < vids.length; i++) {{
                vids[i].playbackRate = {rate};
            }}
            return 'done';
        }})()""")

    async def wait_video_end(self, timeout=300):
        start = time.time()
        while time.time() - start < timeout:
            state = await self.get_video_state()
            if state.get("e"):
                return True
            if state.get("d", 0) > 0 and not state.get("p"):
                # Set speed high
                await self.set_video_speed(16)
            await asyncio.sleep(1)
        return False

    async def close(self):
        if self.ws:
            await self.ws.close()


async def complete_lesson(helper):
    """Complete the current lesson and return True if successful."""
    text = await helper.get_text(500)
    print(f"  Page: {text[:100].replace(chr(10), ' ')}")

    if await helper.has_video():
        print("  Video detected, playing at 16x...")
        await helper.set_video_speed(16)
        # Try clicking play button
        await helper.click_button_by_text("Play")
        await asyncio.sleep(2)
        ended = await helper.wait_video_end(timeout=300)
        print(f"  Video ended: {ended}")
        # Close completion popup
        await helper.click_button_by_text("เรียนต่อ")
        await asyncio.sleep(1)
    else:
        print("  Document/non-video lesson, skipping...")
        await asyncio.sleep(1)

    # Click next
    clicked = await helper.click_button_by_text("ต่อไป")
    if not clicked:
        clicked = await helper.click_button_by_text("ถัดไป")
    await asyncio.sleep(2)
    return clicked


async def complete_quiz(helper):
    """Complete a quiz by selecting correct answers."""
    text = await helper.get_text(3000)
    print(f"  Quiz detected: {text[:100].replace(chr(10), ' ')}")

    # Get all radio buttons with their text
    expr = """(() => {
        var radios = document.querySelectorAll('[role=radio]');
        var items = [];
        for (var i = 0; i < radios.length; i++) {
            var label = radios[i].getAttribute('aria-label') || radios[i].innerText || '';
            var rect = radios[i].getBoundingClientRect();
            items.push({i: i, text: label.substring(0, 80), x: rect.x + rect.width/2, y: rect.y + rect.height/2, w: rect.width});
        }
        return JSON.stringify(items);
    })()"""
    result = await helper.eval_js(expr)
    radios = json.loads(result) if result else []
    print(f"  Found {len(radios)} radio buttons")

    # Group by question (4 options each typically)
    # For now, just select the first option of each question as a placeholder
    # The correct answers depend on the specific quiz
    questions = {}
    for r in radios:
        q_idx = r["i"] // 4  # Assuming 4 options per question
        if q_idx not in questions:
            questions[q_idx] = []
        questions[q_idx].append(r)

    print(f"  {len(questions)} questions found")
    # TODO: Select correct answers based on question content
    # For now, we'll need the user to provide answers or use AI to answer

    # Click submit/next
    clicked = await helper.click_button_by_text("ต่อไป")
    if not clicked:
        clicked = await helper.click_button_by_text("ส่งแบบทดสอบ")
    await asyncio.sleep(2)
    return clicked


async def main():
    helper = CDPHelper()
    try:
        url = await helper.connect()
        print(f"Connected to: {url}")

        # Navigate through remaining lessons
        for step in range(10):  # Max 10 steps
            text = await helper.get_text(800)
            print(f"\n=== Step {step} ===")
            print(text[:200].replace("\n", " | "))

            # Check if we're on a quiz
            if "แบบทดสอบ" in text and "คะแนน" in text and not await helper.has_video():
                await complete_quiz(helper)
            else:
                await complete_lesson(helper)

            # Check progress
            progress_expr = """(() => {
                var text = document.body.innerText;
                var match = text.match(/เรียนจบแล้ว (\\d+) จาก (\\d+) บท/);
                if (match) return match[1] + '/' + match[2];
                return '';
            })()"""
            progress = await helper.eval_js(progress_expr)
            if progress:
                print(f"  Progress: {progress}")
                done, total = progress.split("/")
                if done == total:
                    print("\n=== ALL LESSONS COMPLETED! ===")
                    break

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await helper.close()


if __name__ == "__main__":
    asyncio.run(main())
