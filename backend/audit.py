"""Append-only audit trail at output/audit_trail.json.

The file is a JSON array that only ever grows: each write reads the existing records, adds the
new one, and atomically replaces the file. Nothing is ever cleared between runs. If the file
can't be parsed we stop (raise) rather than overwrite history.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from .config import AUDIT_PATH, AUDIT_TEXT_LIMIT
from .models import AuditRecord

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clip(value: Any, limit: int = AUDIT_TEXT_LIMIT) -> Any:
    """Keep audit records readable: long strings are truncated, structures are kept."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


def append(record: AuditRecord) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = AUDIT_PATH.with_suffix(".lock")
    with _lock, open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # also guards against a second process (e.g. the API + a CLI run)
        records: list = []
        if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
            records = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise RuntimeError(f"{AUDIT_PATH} is not a JSON array; refusing to overwrite it.")
        records.append(record.model_dump(mode="json", exclude_none=True))
        tmp = AUDIT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, AUDIT_PATH)
