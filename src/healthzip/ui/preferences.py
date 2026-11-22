"""Workspace-local viewing choices, written only after an explicit UI action."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import RLock

_LOCK = RLock()


def _path(database):
    database = Path(database).resolve()
    identity = hashlib.sha256(str(database).encode()).hexdigest()[:20]
    return database.parent / ".healthzip-views" / (identity + ".json")


def load_preferences(database):
    path = _path(database)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_preferences(database, **changes):
    path = _path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        # An advisory lock also protects independent Streamlit processes.
        import fcntl
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = {**load_preferences(database), **changes}
            descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(value, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def persist_widget(database, widget_key, preference_key):
    import streamlit as st
    save_preferences(database, **{preference_key: st.session_state[widget_key]})
