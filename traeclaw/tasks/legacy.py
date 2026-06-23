from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def project_root() -> Path:
    if os.environ.get("TRAECLAW_PROJECT_ROOT"):
        return Path(os.environ["TRAECLAW_PROJECT_ROOT"]).resolve()
    return Path(__file__).resolve().parents[3]


def db_path() -> Path:
    if os.environ.get("TRAECLAW_DB_PATH"):
        return Path(os.environ["TRAECLAW_DB_PATH"]).resolve()
    return project_root() / "data" / "traeclaw.sqlite3"


def rewrite_legacy_source(source: str, root: str | Path, shared_db: str | Path) -> str:
    root_text = str(Path(root))
    db_text = str(Path(shared_db))
    db_text_escaped = db_text.replace("\\", "\\\\")
    
    # Replace WORKSPACE and ROOT variables
    source = source.replace(
        'WORKSPACE = "/home/eric/Documents/workspace"',
        f"WORKSPACE = {root_text!r}",
    )
    source = source.replace(
        "WORKSPACE = '/home/eric/Documents/workspace'",
        f"WORKSPACE = {root_text!r}",
    )
    source = source.replace(
        'WORKSPACE = "/home/eric/Documents/traeclaw"',
        f"WORKSPACE = {root_text!r}",
    )
    source = source.replace(
        "WORKSPACE = '/home/eric/Documents/traeclaw'",
        f"WORKSPACE = {root_text!r}",
    )
    source = source.replace(
        "ROOT = Path('/home/eric/Documents/workspace')",
        f"ROOT = Path({root_text!r})",
    )
    source = source.replace(
        'ROOT = Path("/home/eric/Documents/workspace")',
        f"ROOT = Path({root_text!r})",
    )

    # Redirect DB_PATH variables to unified traeclaw.sqlite3
    source = re.sub(
        r'DB_PATH\s*=\s*f"\{STATE_DIR\}/[^"]+"',
        f"DB_PATH = {db_text_escaped!r}",
        source,
    )
    source = re.sub(
        r"DB_PATH\s*=\s*f'\{STATE_DIR\}/[^']+'",
        f"DB_PATH = {db_text_escaped!r}",
        source,
    )
    source = re.sub(
        r"DB_PATH\s*=\s*Path\('/home/eric/Documents/workspace/state/[^']+'\)",
        f"DB_PATH = Path({db_text_escaped!r})",
        source,
    )
    source = re.sub(
        r'DB_PATH\s*=\s*Path\("/home/eric/Documents/workspace/state/[^"]+"\)',
        f"DB_PATH = Path({db_text_escaped!r})",
        source,
    )
    source = re.sub(
        r"DEFAULT_DB\s*=\s*ROOT\s*/\s*'state'[^'\n]+",
        f"DEFAULT_DB = Path({db_text_escaped!r})",
        source,
    )
    source = re.sub(
        r'DEFAULT_DB\s*=\s*ROOT\s*/\s*"state"[^"\n]+',
        f"DEFAULT_DB = Path({db_text_escaped!r})",
        source,
    )

    # Relocate legacy helper paths into the standalone project layout.
    source = source.replace("ROOT / 'skills' / 'dida-todo-sync' / 'scripts' / 'dida_sync.py'", "ROOT / 'scripts' / 'dida' / 'dida_sync.py'")
    source = source.replace('ROOT / "skills" / "dida-todo-sync" / "scripts" / "dida_sync.py"', 'ROOT / "scripts" / "dida" / "dida_sync.py"')

    return source


def run_legacy_python(script: str | Path, argv: list[str] | None = None) -> int:
    root = project_root()
    script_path = (root / script).resolve()
    if not script_path.exists():
        fallback_path = (root / "code" / script).resolve()
        if fallback_path.exists():
            script_path = fallback_path
        else:
            raise SystemExit(f"legacy script not found: {script_path}")
    source = script_path.read_text(encoding="utf-8")
    
    # Enforce default socket timeout to prevent network hangs on slow APIs or proxies
    import socket
    socket.setdefaulttimeout(60)

    rewritten = rewrite_legacy_source(source, root, db_path())
    old_argv = sys.argv[:]
    old_path = sys.path[:]
    try:
        sys.argv = [str(script_path)] + (argv or [])
        sys.path.insert(0, str(script_path.parent))
        globals_dict = {
            "__name__": "__main__",
            "__file__": str(script_path),
            "__package__": None,
        }
        exec(compile(rewritten, str(script_path), "exec"), globals_dict)
    finally:
        sys.argv = old_argv
        sys.path[:] = old_path
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run legacy Python script against shared Traeclaw DB")
    parser.add_argument("script")
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    return run_legacy_python(args.script, args.script_args)


if __name__ == "__main__":
    raise SystemExit(main())
