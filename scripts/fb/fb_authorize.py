#!/usr/bin/env python3
import sys
import os
import subprocess
from pathlib import Path

# Add project root to python path to import traeclaw modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from traeclaw.db import AppDatabase

def main():
    db_file = os.environ.get("TRAECLAW_DB_PATH") or str(PROJECT_ROOT / "data" / "traeclaw.sqlite3")
    db = AppDatabase(db_file)
    
    # Sync settings to disk
    state_rel = "state/facebook/fb_storage_state.json"
    groups_rel = "state/facebook/fb_groups.json"
    
    state_file = PROJECT_ROOT / state_rel
    groups_file = PROJECT_ROOT / groups_rel
    
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Write existing state and groups from DB to disk
    state_content = db.get_setting(f"file:{state_rel}", "")
    groups_content = db.get_setting(f"file:{groups_rel}", "")
    
    # If state_content is empty, write a default empty object
    if not state_content:
        state_content = "{}"
    state_file.write_text(state_content, encoding="utf-8")
    
    if groups_content:
        groups_file.write_text(groups_content, encoding="utf-8")
    
    try:
        if os.name == 'nt':
            # On Windows, run the node script directly instead of relying on bash
            js_script = SCRIPT_DIR / "fb_yesterday_summary.js"
            subprocess.run(
                ["node", str(js_script), "--login", "--state-file", str(state_file), "--config", str(groups_file)],
                cwd=str(PROJECT_ROOT),
                check=True
            )
        else:
            # On macOS/Linux, run the sh script
            sh_script = SCRIPT_DIR / "fb_yesterday_summary.sh"
            subprocess.run(
                ["bash", str(sh_script), "--login"],
                cwd=str(PROJECT_ROOT),
                check=True
            )
        
        # Read updated state from disk and save to DB
        if state_file.exists():
            updated_state = state_file.read_text(encoding="utf-8")
            db.set_setting(f"file:{state_rel}", updated_state)
            print("Successfully updated and saved Facebook login session to database!")
    except Exception as e:
        print(f"Error during authorization: {e}", file=sys.stderr)
    finally:
        # Clean up
        if state_file.exists():
            state_file.unlink()
        if groups_file.exists():
            groups_file.unlink()
            
        # Clean up empty parent directories
        parent = state_file.parent
        while parent != PROJECT_ROOT / "state" and parent != PROJECT_ROOT:
            try:
                parent.rmdir()
                parent = parent.parent
            except Exception:
                break

if __name__ == "__main__":
    main()
