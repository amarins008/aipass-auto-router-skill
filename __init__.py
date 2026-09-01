#!/usr/bin/env python3
"""
AI-Pass Auto Router - Skill Init Hook
Auto-registers slash commands when skill loads.
Place this in the skill directory and it will be auto-discovered.
"""

import sys
from pathlib import Path

# Auto-register slash commands on import
def _register():
    try:
        skill_dir = Path(__file__).parent.parent
        scripts_dir = skill_dir / "scripts"
        sys.path.insert(0, str(scripts_dir))

        from register_slash_commands import register_aipass_commands
        register_aipass_commands()
    except Exception as e:
        # Silent fail - slash commands are optional enhancement
        pass


# Run on import
_register()