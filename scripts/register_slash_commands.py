#!/usr/bin/env python3
"""
AI-Pass Auto Router - Slash Command Registration
Registers /aipass-* commands with Hermes.
Run this once after installing the skill to enable slash commands.
"""

import sys
from pathlib import Path

# Add Hermes to path if needed
HERMES_ROOT = Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"
if HERMES_ROOT.exists():
    sys.path.insert(0, str(HERMES_ROOT))

try:
    from hermes_cli.commands import COMMAND_REGISTRY, CommandSpec
except ImportError:
    COMMAND_REGISTRY = None
    CommandSpec = None


def register_aipass_commands():
    """Register /aipass-* slash commands."""

    # /aipass-route <task-class> <prompt>
    if COMMAND_REGISTRY is None:
        return
    COMMAND_REGISTRY["aipass-route"] = CommandSpec(
        name="aipass-route",
        aliases=["aipass-r"],
        description="Route prompt to optimal model on ThaiAI-Pass for task class",
        usage="/aipass-route <code|deep-reasoning|thai-content|fast|research> <prompt>",
        handler=_handle_aipass_route,
        help_text="""
Route a prompt through ThaiAI-Pass using the best model for the task class.

Task classes:
  code            - Code generation, debugging, technical tasks
  deep-reasoning  - Complex reasoning, chain-of-thought
  thai-content    - Thai language understanding/generation
  fast            - Low latency, quick responses
  research        - Broad knowledge, long context

Examples:
  /aipass-route code "Write a Python async HTTP client with retries"
  /aipass-route thai-content "แปลประโยคนี้เป็นภาษาอังกฤษ"
  /aipass-route fast "Quick summary of this article"
""",
    )

    # /aipass-status
    COMMAND_REGISTRY["aipass-status"] = CommandSpec(
        name="aipass-status",
        aliases=["aipass-s"],
        description="Show model availability, cooldowns, and last used times",
        usage="/aipass-status",
        handler=_handle_aipass_status,
        help_text="Display all registered models with their current status (available/cooldown), task classes, and cooldown expiry.",
    )

    # /aipass-scan
    COMMAND_REGISTRY["aipass-scan"] = CommandSpec(
        name="aipass-scan",
        aliases=["aipass-scan"],
        description="Scan ThaiAI-Pass tab for available models",
        usage="/aipass-scan",
        handler=_handle_aipass_scan,
        help_text="Connect to the active ThaiAI-Pass browser tab via CDP and discover available models in the model selector dropdown.",
    )

    # /aipass-cooldown <model-id> [minutes]
    COMMAND_REGISTRY["aipass-cooldown"] = CommandSpec(
        name="aipass-cooldown",
        aliases=["aipass-cd"],
        description="Set or clear model cooldown manually",
        usage="/aipass-cooldown <model-id> [minutes]  # set\n/aipass-cooldown --clear <model-id>        # clear",
        handler=_handle_aipass_cooldown,
        help_text="""
Manually set or clear cooldown for a model.

Set:  /aipass-cooldown gpt-4o 15    # 15-minute cooldown (default)
Clear: /aipass-cooldown --clear gpt-4o
""",
    )

    print("Registered /aipass-route, /aipass-status, /aipass-scan, /aipass-cooldown")


async def _handle_aipass_route(args: list, session) -> str:
    """Handler for /aipass-route."""
    if len(args) < 2:
        return "Usage: /aipass-route <task-class> <prompt>"

    task_class = args[0]
    prompt = " ".join(args[1:])

    valid_classes = ["code", "deep-reasoning", "thai-content", "fast", "research"]
    if task_class not in valid_classes:
        return f"Invalid task class. Choose from: {', '.join(valid_classes)}"

    # Import and run bridge
    skill_dir = Path.home() / "AppData" / "Local" / "hermes" / "skills" / "autonomous-ai-agents" / "aipass-auto-router"
    sys.path.insert(0, str(skill_dir / "scripts"))

    from aipass_bridge import AIPassBridge

    bridge = AIPassBridge()
    result = await bridge.route_prompt(task_class, prompt)

    if result.success:
        return f"**Model:** {result.model_used}\n\n{result.response}"
    else:
        return f"❌ **Error:** {result.error}\nModel: {result.model_used}"


async def _handle_aipass_status(args: list, session) -> str:
    """Handler for /aipass-status."""
    skill_dir = Path.home() / "AppData" / "Local" / "hermes" / "skills" / "autonomous-ai-agents" / "aipass-auto-router"
    sys.path.insert(0, str(skill_dir / "scripts"))

    from check_models import ModelStatusManager
    from pathlib import Path

    mgr = ModelStatusManager(skill_dir / "state" / "model_status.json")
    mgr._expire_cooldowns()

    if not mgr.models:
        return "No models registered. Run `/aipass-scan` first."

    lines = ["**Model Status:**\n"]
    lines.append(f"{'Model ID':<30} {'Name':<25} {'Status':<12} {'Classes':<25} {'Cooldown Until':<25}")
    lines.append("-" * 120)

    for m in sorted(mgr.models.values(), key=lambda x: (not x.available, x.priority)):
        status = "✅ AVAILABLE" if m.available else "⏳ COOLDOWN"
        if m.error_count > 0:
            status += f" (err: {m.error_count})"
        classes = ", ".join(m.task_classes) if m.task_classes else "—"
        cd = m.cooldown_until or "—"
        lines.append(f"{m.id:<30} {m.name:<25} {status:<12} {classes:<25} {cd:<25}")

    return "\n".join(lines)


async def _handle_aipass_scan(args: list, session) -> str:
    """Handler for /aipass-scan."""
    skill_dir = Path.home() / "AppData" / "Local" / "hermes" / "skills" / "autonomous-ai-agents" / "aipass-auto-router"
    sys.path.insert(0, str(skill_dir / "scripts"))

    from aipass_bridge import AIPassBridge

    bridge = AIPassBridge()
    models = await bridge.scan_models()

    if not models:
        return "No models found. Ensure:\n1. Chrome/Brave running with --remote-debugging-port=9222\n2. ThaiAI-Pass tab open at https://de.aipass.net/chat\n3. You're logged in"

    lines = [f"**Discovered {len(models)} models:**\n"]
    for m in models:
        lines.append(f"  • **{m.id}** — {m.name} (classes: {', '.join(m.task_classes)}, priority: {m.priority})")

    return "\n".join(lines)


async def _handle_aipass_cooldown(args: list, session) -> str:
    """Handler for /aipass-cooldown."""
    skill_dir = Path.home() / "AppData" / "Local" / "hermes" / "skills" / "autonomous-ai-agents" / "aipass-auto-router"
    sys.path.insert(0, str(skill_dir / "scripts"))

    from check_models import ModelStatusManager

    mgr = ModelStatusManager(skill_dir / "state" / "model_status.json")

    if not args:
        return "Usage: /aipass-cooldown <model-id> [minutes]  OR  /aipass-cooldown --clear <model-id>"

    if args[0] == "--clear":
        if len(args) < 2:
            return "Usage: /aipass-cooldown --clear <model-id>"
        mgr.clear_cooldown(args[1])
        return f"Cleared cooldown for {args[1]}"

    model_id = args[0]
    minutes = int(args[1]) if len(args) > 1 else 15
    mgr.set_cooldown(model_id, minutes)
    return f"Set {minutes}-minute cooldown for {model_id}"


if __name__ == "__main__":
    # For direct execution: just register (used in skill init)
    register_aipass_commands()
    print("Slash commands registered. Restart session or run /reload-skills to activate.")