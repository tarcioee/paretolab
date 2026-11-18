"""``state.json``: what the experiment is doing now, for the CLI and the web interface.

The source of truth for what is finished is the set of ``result.json`` files; this file only reports progress.
"""
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = "state.json"
PAUSE_FILE = "PAUSE"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    for attempt in range(5):           # on Windows a reader may hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def read_state(output_dir) -> dict | None:
    try:
        return json.loads((Path(output_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def free_disk_gb(path) -> float:
    test = os.environ.get("PARETOLAB_TEST_FREE_DISK_GB")
    if test:
        return float(test)
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free / 1e9


def format_duration(seconds) -> str:
    if seconds is None:
        return "?"
    seconds = round(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else (f"{m}m{s:02d}s" if m else f"{s}s")
