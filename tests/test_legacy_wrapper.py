from pathlib import Path

from traeclaw.tasks.legacy import rewrite_legacy_source


def test_rewrite_legacy_source_redirects_workspace_and_db_path(tmp_path):
    root = tmp_path / "project"
    db_path = tmp_path / "shared.sqlite3"
    source = """
import os
from pathlib import Path
WORKSPACE = "/home/eric/Documents/workspace"
STATE_DIR = f"{WORKSPACE}/state/mfdb"
DB_PATH = f"{STATE_DIR}/maskphone_monitor.db"
DB_PATH = Path('/home/eric/Documents/workspace/state/tycp/data/dlt_history.sqlite3')
"""

    rewritten = rewrite_legacy_source(source, root, db_path)

    assert 'WORKSPACE = "/home/eric/Documents/workspace"' not in rewritten
    assert f"WORKSPACE = {str(root)!r}" in rewritten
    assert f"DB_PATH = {str(db_path)!r}" in rewritten
    assert f"Path({str(db_path)!r})" in rewritten
