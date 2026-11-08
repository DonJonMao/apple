"""SQLite persistence with idempotent imports."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from healthzip.normalize import stable_fingerprint

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO schema_meta(key,value) VALUES ('schema_version','1');
CREATE TABLE IF NOT EXISTS import_batch (
 id INTEGER PRIMARY KEY, file_sha256 TEXT NOT NULL, file_name TEXT, file_size_bytes INTEGER,
 exported_at TEXT, imported_at TEXT NOT NULL, status TEXT NOT NULL, xml_member_path TEXT,
 records_seen INTEGER DEFAULT 0, records_inserted INTEGER DEFAULT 0, records_deduplicated INTEGER DEFAULT 0,
 records_skipped INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0, date_min TEXT, date_max TEXT,
 unknown_type_counts_json TEXT DEFAULT '{}', error_samples_json TEXT DEFAULT '[]',
 source_kind TEXT NOT NULL DEFAULT 'apple_zip', source_ref TEXT, received_at TEXT,
 records_new INTEGER DEFAULT 0, records_duplicate INTEGER DEFAULT 0,
 records_updated INTEGER DEFAULT 0, records_deleted INTEGER DEFAULT 0, records_invalid INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_batch_hash ON import_batch(file_sha256);
CREATE TABLE IF NOT EXISTS health_sample (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, import_batch_id INTEGER NOT NULL REFERENCES import_batch(id),
 raw_type TEXT NOT NULL, canonical_type TEXT, raw_value TEXT, raw_unit TEXT, normalized_value REAL,
 normalized_unit TEXT, unit_status TEXT, category_value TEXT, start_utc TEXT, end_utc TEXT, creation_utc TEXT,
 local_datetime TEXT, local_date TEXT, utc_offset_minutes INTEGER, source_name TEXT, source_version TEXT,
 device TEXT, metadata_json TEXT DEFAULT '{}', quality_flags_json TEXT DEFAULT '{}', created_at TEXT NOT NULL,
 source_kind TEXT NOT NULL DEFAULT 'apple_zip', source_record_id TEXT, logical_key TEXT,
 record_status TEXT NOT NULL DEFAULT 'active', supersedes_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sample_type_date ON health_sample(canonical_type, local_date);
CREATE INDEX IF NOT EXISTS idx_sample_start ON health_sample(start_utc);
CREATE TABLE IF NOT EXISTS workout (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, import_batch_id INTEGER NOT NULL REFERENCES import_batch(id),
 activity_type TEXT, start_utc TEXT, end_utc TEXT, local_date TEXT, duration_seconds REAL,
 distance_value REAL, distance_unit TEXT, energy_value REAL, energy_unit TEXT, source_name TEXT, source_version TEXT,
 device TEXT, metadata_json TEXT DEFAULT '{}', suspected_duplicate INTEGER DEFAULT 0,
 source_kind TEXT NOT NULL DEFAULT 'apple_zip', source_record_id TEXT, logical_key TEXT,
 record_status TEXT NOT NULL DEFAULT 'active', supersedes_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_workout_date ON workout(local_date);
CREATE TABLE IF NOT EXISTS workout_statistic (
 id INTEGER PRIMARY KEY, workout_id INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
 raw_type TEXT, statistic_start TEXT, statistic_end TEXT, average_value REAL, minimum_value REAL,
 maximum_value REAL, sum_value REAL, unit TEXT
);
CREATE TABLE IF NOT EXISTS workout_event (
 id INTEGER PRIMARY KEY, workout_id INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
 event_type TEXT, event_date TEXT, duration_seconds REAL, metadata_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS activity_summary (
 id INTEGER PRIMARY KEY, import_batch_id INTEGER NOT NULL REFERENCES import_batch(id), summary_date TEXT,
 active_energy REAL, active_energy_goal REAL, exercise_minutes REAL, exercise_minutes_goal REAL,
 stand_hours REAL, stand_hours_goal REAL, UNIQUE(import_batch_id, summary_date)
);
CREATE TABLE IF NOT EXISTS strength_session (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, session_date TEXT, started_at TEXT, name TEXT,
 source TEXT, notes TEXT, import_batch_id INTEGER
);
CREATE TABLE IF NOT EXISTS strength_set (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, session_id INTEGER REFERENCES strength_session(id),
 set_date TEXT, started_at TEXT, exercise_id TEXT, exercise_name TEXT, equipment TEXT, variation TEXT,
 side TEXT, set_number INTEGER, weight_kg REAL, reps INTEGER, rir REAL, rpe REAL, warmup INTEGER,
 range_of_motion TEXT, notes TEXT, import_batch_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_strength_key ON strength_set(exercise_name,equipment,variation,set_date);
CREATE TABLE IF NOT EXISTS nutrition_day (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, day TEXT, energy_kcal REAL, protein_g REAL,
 carbohydrates_g REAL, fat_g REAL, log_status TEXT NOT NULL, source TEXT, notes TEXT, import_batch_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nutrition_day ON nutrition_day(day);
CREATE TABLE IF NOT EXISTS body_measurement (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, measured_at TEXT, local_date TEXT, body_part TEXT,
 value REAL, unit TEXT, canonical_type TEXT, source TEXT, notes TEXT, import_batch_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_measure_date ON body_measurement(canonical_type,local_date);
CREATE TABLE IF NOT EXISTS subjective_log (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, day TEXT, energy_level REAL, fatigue REAL, soreness REAL,
 stress REAL, sleep_quality REAL, pain_location TEXT, pain_level REAL, illness_or_travel TEXT, notes TEXT,
 import_batch_id INTEGER
);
CREATE TABLE IF NOT EXISTS cycle_event (
 id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, event_date TEXT, canonical_type TEXT, category_value TEXT,
 intensity REAL, source TEXT, confirmed INTEGER, notes TEXT, import_batch_id INTEGER
);
CREATE TABLE IF NOT EXISTS daily_feature (
 id INTEGER PRIMARY KEY, feature_key TEXT UNIQUE, local_date TEXT, metric TEXT, value REAL, unit TEXT,
 sample_count INTEGER, quality_state TEXT, window_start TEXT, window_end TEXT, algorithm_version TEXT,
 source_ids_json TEXT DEFAULT '[]', limitations_json TEXT DEFAULT '[]', computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insight (
 id TEXT PRIMARY KEY, title TEXT, status TEXT, window_start TEXT, window_end TEXT, summary TEXT,
 facts_json TEXT, limitations_json TEXT, allowed_actions_json TEXT, source_feature_ids_json TEXT,
 algorithm_version TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_source (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 config_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
 last_cursor TEXT, last_success_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_file (
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sync_source(id) ON DELETE CASCADE,
 path TEXT NOT NULL, inode INTEGER, size_bytes INTEGER, mtime_ns INTEGER, content_hash TEXT,
 format TEXT NOT NULL, last_offset INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
 last_error TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(source_id, path)
);
CREATE INDEX IF NOT EXISTS idx_sync_file_source ON sync_file(source_id, status);
CREATE TABLE IF NOT EXISTS ingest_event (
 id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sync_source(id), batch_id INTEGER REFERENCES import_batch(id),
 upstream_id TEXT, event_kind TEXT NOT NULL, payload_hash TEXT, received_at TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_event_upstream ON ingest_event(source_id, upstream_id);
"""

CURRENT_SCHEMA_VERSION = 2


def _json(value: Any) -> str:
    return json.dumps(
        value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str
    )


class Repository:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate_schema()
        self.conn.commit()

    def _migrate_schema(self) -> None:
        """Upgrade v1 databases without replacing user data.

        The original prototype executed a CREATE-only schema on every open.
        Incremental sync adds columns to existing tables, so migrations must be
        explicit and idempotent.  SQLite has no ``ADD COLUMN IF NOT EXISTS``;
        inspect the current columns before applying each addition.
        """
        row = self.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        version = int(row[0]) if row and str(row[0]).isdigit() else 1

        additions = {
            "import_batch": {
                "source_kind": "TEXT NOT NULL DEFAULT 'apple_zip'",
                "source_ref": "TEXT",
                "received_at": "TEXT",
                "records_new": "INTEGER DEFAULT 0",
                "records_duplicate": "INTEGER DEFAULT 0",
                "records_updated": "INTEGER DEFAULT 0",
                "records_deleted": "INTEGER DEFAULT 0",
                "records_invalid": "INTEGER DEFAULT 0",
            },
            "health_sample": {
                "source_kind": "TEXT NOT NULL DEFAULT 'apple_zip'",
                "source_record_id": "TEXT",
                "logical_key": "TEXT",
                "record_status": "TEXT NOT NULL DEFAULT 'active'",
                "supersedes_id": "INTEGER",
            },
            "workout": {
                "source_kind": "TEXT NOT NULL DEFAULT 'apple_zip'",
                "source_record_id": "TEXT",
                "logical_key": "TEXT",
                "record_status": "TEXT NOT NULL DEFAULT 'active'",
                "supersedes_id": "INTEGER",
            },
        }
        for table, columns in additions.items():
            existing = {
                str(row[1]) for row in self.conn.execute(f"PRAGMA table_info({table})")
            }
            for name, declaration in columns.items():
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

        self.conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_sample_source_record ON health_sample(source_kind, source_record_id);
            CREATE INDEX IF NOT EXISTS idx_sample_logical_key ON health_sample(source_kind, logical_key);
            CREATE INDEX IF NOT EXISTS idx_workout_source_record ON workout(source_kind, source_record_id);
            CREATE INDEX IF NOT EXISTS idx_workout_logical_key ON workout(source_kind, logical_key);
            CREATE TABLE IF NOT EXISTS sync_source (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
                last_cursor TEXT, last_success_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_file (
                id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sync_source(id) ON DELETE CASCADE,
                path TEXT NOT NULL, inode INTEGER, size_bytes INTEGER, mtime_ns INTEGER, content_hash TEXT,
                format TEXT NOT NULL, last_offset INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                UNIQUE(source_id, path)
            );
            CREATE INDEX IF NOT EXISTS idx_sync_file_source ON sync_file(source_id, status);
            CREATE TABLE IF NOT EXISTS ingest_event (
                id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sync_source(id), batch_id INTEGER REFERENCES import_batch(id),
                upstream_id TEXT, event_kind TEXT NOT NULL, payload_hash TEXT, received_at TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ingest_event_upstream ON ingest_event(source_id, upstream_id);
            """
        )
        if version < CURRENT_SCHEMA_VERSION:
            self.conn.execute(
                "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(CURRENT_SCHEMA_VERSION),),
            )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def create_batch(
        self,
        *,
        file_sha256: str,
        file_name: str,
        file_size: int,
        xml_member_path: str,
        source_kind: str = "apple_zip",
        source_ref: Optional[str] = None,
        received_at: Optional[str] = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO import_batch(file_sha256,file_name,file_size_bytes,imported_at,status,xml_member_path,source_kind,source_ref,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                file_sha256,
                file_name,
                file_size,
                datetime.now(timezone.utc).isoformat(),
                "running",
                xml_member_path,
                source_kind,
                source_ref,
                received_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def existing_completed_batch(self, file_sha256: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM import_batch WHERE file_sha256=? AND status='completed' ORDER BY id DESC LIMIT 1",
            (file_sha256,),
        ).fetchone()

    def finish_batch(self, batch_id: int, **fields: Any) -> None:
        allowed = {
            "exported_at",
            "status",
            "records_seen",
            "records_inserted",
            "records_deduplicated",
            "records_skipped",
            "errors_count",
            "date_min",
            "date_max",
            "unknown_type_counts_json",
            "error_samples_json",
            "source_kind",
            "source_ref",
            "received_at",
            "records_new",
            "records_duplicate",
            "records_updated",
            "records_deleted",
            "records_invalid",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        sql = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE import_batch SET {sql} WHERE id=?", (*fields.values(), batch_id))
        self.conn.commit()

    def insert_sample(self, batch_id: int, data: dict[str, Any]) -> bool:
        data = dict(data)
        data.setdefault("source_kind", "apple_zip")
        data.setdefault("record_status", "active")
        cols = [
            "fingerprint",
            "import_batch_id",
            "raw_type",
            "canonical_type",
            "raw_value",
            "raw_unit",
            "normalized_value",
            "normalized_unit",
            "unit_status",
            "category_value",
            "start_utc",
            "end_utc",
            "creation_utc",
            "local_datetime",
            "local_date",
            "utc_offset_minutes",
            "source_name",
            "source_version",
            "device",
            "metadata_json",
            "quality_flags_json",
            "created_at",
            "source_kind",
            "source_record_id",
            "logical_key",
            "record_status",
            "supersedes_id",
        ]
        vals = [data.get(c) if c != "import_batch_id" else batch_id for c in cols]
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO health_sample({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            vals,
        )
        return cur.rowcount == 1

    def insert_incremental_sample(self, batch_id: int, data: dict[str, Any]) -> str:
        """Insert one sample and classify its idempotency outcome.

        A source record ID identifies the logical object when an exporter
        provides one.  A changed object is retained for provenance while the
        previous version becomes ``superseded``; analytics only use active rows.
        """
        data = dict(data)
        data.setdefault("source_kind", "incremental")
        data.setdefault("record_status", "active")
        source_kind = data.get("source_kind") or "incremental"
        source_record_id = data.get("source_record_id")
        logical_key = data.get("logical_key")
        existing = None
        if source_record_id:
            existing = self.one(
                "SELECT * FROM health_sample WHERE source_kind=? AND source_record_id=? "
                "AND record_status='active' ORDER BY id DESC LIMIT 1",
                (source_kind, str(source_record_id)),
            )
        elif logical_key:
            existing = self.one(
                "SELECT * FROM health_sample WHERE source_kind=? AND logical_key=? "
                "AND record_status='active' ORDER BY id DESC LIMIT 1",
                (source_kind, str(logical_key)),
            )
        if existing is not None:
            if existing["fingerprint"] == data.get("fingerprint"):
                return "duplicate"
            collision = self.one(
                "SELECT * FROM health_sample WHERE fingerprint=?", (data.get("fingerprint"),)
            )
            if collision is not None:
                if collision["record_status"] == "superseded":
                    self.conn.execute(
                        "UPDATE health_sample SET record_status='superseded' WHERE id=?",
                        (int(existing["id"]),),
                    )
                    self.conn.execute(
                        "UPDATE health_sample SET record_status='active',import_batch_id=?,supersedes_id=NULL WHERE id=?",
                        (batch_id, int(collision["id"])),
                    )
                    return "updated"
                return "duplicate"
            previous = self.one(
                "SELECT * FROM health_sample WHERE source_kind=? AND fingerprint=? "
                "AND record_status='superseded' ORDER BY id DESC LIMIT 1",
                (source_kind, data.get("fingerprint")),
            )
            if previous is not None:
                self.conn.execute(
                    "UPDATE health_sample SET record_status='superseded' WHERE id=?",
                    (int(existing["id"]),),
                )
                self.conn.execute(
                    "UPDATE health_sample SET record_status='active',import_batch_id=?,supersedes_id=NULL WHERE id=?",
                    (batch_id, int(previous["id"])),
                )
                return "updated"
            data["supersedes_id"] = int(existing["id"])
            self.conn.execute(
                "UPDATE health_sample SET record_status='superseded' WHERE id=?", (int(existing["id"]),)
            )
            if self.insert_sample(batch_id, data):
                return "updated"
            return "duplicate"
        return "new" if self.insert_sample(batch_id, data) else "duplicate"

    def insert_workout(self, batch_id: int, data: dict[str, Any]) -> tuple[Optional[int], bool]:
        data = dict(data)
        data.setdefault("source_kind", "apple_zip")
        data.setdefault("record_status", "active")
        cols = [
            "fingerprint",
            "import_batch_id",
            "activity_type",
            "start_utc",
            "end_utc",
            "local_date",
            "duration_seconds",
            "distance_value",
            "distance_unit",
            "energy_value",
            "energy_unit",
            "source_name",
            "source_version",
            "device",
            "metadata_json",
            "suspected_duplicate",
            "source_kind",
            "source_record_id",
            "logical_key",
            "record_status",
            "supersedes_id",
        ]
        # Preserve overlapping sessions from different sources, but mark them for review.
        overlap = self.conn.execute(
            "SELECT 1 FROM workout WHERE activity_type=? AND start_utc=? AND end_utc=? AND source_name IS NOT ? LIMIT 1",
            (
                data.get("activity_type"),
                data.get("start_utc"),
                data.get("end_utc"),
                data.get("source_name"),
            ),
        ).fetchone()
        if overlap:
            data = dict(data)
            data["suspected_duplicate"] = 1
        vals = [data.get(c) if c != "import_batch_id" else batch_id for c in cols]
        before = self.conn.total_changes
        self.conn.execute(
            f"INSERT OR IGNORE INTO workout({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            vals,
        )
        row = self.conn.execute(
            "SELECT id FROM workout WHERE fingerprint=?", (data["fingerprint"],)
        ).fetchone()
        return (int(row[0]) if row else None), self.conn.total_changes > before

    def insert_incremental_workout(self, batch_id: int, data: dict[str, Any]) -> str:
        data = dict(data)
        data.setdefault("source_kind", "incremental")
        data.setdefault("record_status", "active")
        source_kind = data.get("source_kind") or "incremental"
        source_record_id = data.get("source_record_id")
        logical_key = data.get("logical_key")
        existing = None
        if source_record_id:
            existing = self.one(
                "SELECT * FROM workout WHERE source_kind=? AND source_record_id=? "
                "AND record_status='active' ORDER BY id DESC LIMIT 1",
                (source_kind, str(source_record_id)),
            )
        elif logical_key:
            existing = self.one(
                "SELECT * FROM workout WHERE source_kind=? AND logical_key=? "
                "AND record_status='active' ORDER BY id DESC LIMIT 1",
                (source_kind, str(logical_key)),
            )
        if existing is not None:
            if existing["fingerprint"] == data.get("fingerprint"):
                return "duplicate"
            collision = self.one("SELECT * FROM workout WHERE fingerprint=?", (data.get("fingerprint"),))
            if collision is not None:
                if collision["record_status"] == "superseded":
                    self.conn.execute(
                        "UPDATE workout SET record_status='superseded' WHERE id=?", (int(existing["id"]),)
                    )
                    self.conn.execute(
                        "UPDATE workout SET record_status='active',import_batch_id=?,supersedes_id=NULL WHERE id=?",
                        (batch_id, int(collision["id"])),
                    )
                    return "updated"
                return "duplicate"
            previous = self.one(
                "SELECT * FROM workout WHERE source_kind=? AND fingerprint=? "
                "AND record_status='superseded' ORDER BY id DESC LIMIT 1",
                (source_kind, data.get("fingerprint")),
            )
            if previous is not None:
                self.conn.execute(
                    "UPDATE workout SET record_status='superseded' WHERE id=?", (int(existing["id"]),)
                )
                self.conn.execute(
                    "UPDATE workout SET record_status='active',import_batch_id=?,supersedes_id=NULL WHERE id=?",
                    (batch_id, int(previous["id"])),
                )
                return "updated"
            data["supersedes_id"] = int(existing["id"])
            self.conn.execute(
                "UPDATE workout SET record_status='superseded' WHERE id=?", (int(existing["id"]),)
            )
            workout_id, inserted = self.insert_workout(batch_id, data)
            if inserted and workout_id:
                for stat in data.get("statistics", []):
                    self.insert_workout_stat(workout_id, stat)
                for event in data.get("events", []):
                    self.insert_workout_event(workout_id, event)
                return "updated"
            return "duplicate"
        workout_id, inserted = self.insert_workout(batch_id, data)
        if inserted and workout_id:
            for stat in data.get("statistics", []):
                self.insert_workout_stat(workout_id, stat)
            for event in data.get("events", []):
                self.insert_workout_event(workout_id, event)
        return "new" if inserted else "duplicate"

    def get_or_create_sync_source(
        self, name: str, kind: str, config: Optional[dict[str, Any]] = None
    ) -> sqlite3.Row:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO sync_source(name,kind,config_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?)",
            (name, kind, _json(config or {}), now, now),
        )
        self.conn.execute(
            "UPDATE sync_source SET kind=?,config_json=?,updated_at=? WHERE name=?",
            (kind, _json(config or {}), now, name),
        )
        self.conn.commit()
        row = self.one("SELECT * FROM sync_source WHERE name=?", (name,))
        if row is None:
            raise RuntimeError(f"sync source was not created: {name}")
        return row

    def get_sync_file(self, source_id: int, path: str) -> Optional[sqlite3.Row]:
        return self.one("SELECT * FROM sync_file WHERE source_id=? AND path=?", (source_id, path))

    def upsert_sync_file(self, source_id: int, path: str, fields: dict[str, Any]) -> sqlite3.Row:
        now = datetime.now(timezone.utc).isoformat()
        current = self.get_sync_file(source_id, path)
        if current is None:
            self.conn.execute(
                "INSERT INTO sync_file(source_id,path,inode,size_bytes,mtime_ns,content_hash,format,last_offset,status,last_error,first_seen_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    path,
                    fields.get("inode"),
                    fields.get("size_bytes"),
                    fields.get("mtime_ns"),
                    fields.get("content_hash"),
                    fields.get("format", "auto"),
                    int(fields.get("last_offset", 0)),
                    fields.get("status", "pending"),
                    fields.get("last_error"),
                    now,
                    now,
                ),
            )
        else:
            updates = {
                k: fields[k]
                for k in (
                    "inode",
                    "size_bytes",
                    "mtime_ns",
                    "content_hash",
                    "format",
                    "last_offset",
                    "status",
                    "last_error",
                )
                if k in fields
            }
            updates["last_seen_at"] = now
            if updates:
                sql = ",".join(f"{k}=?" for k in updates)
                self.conn.execute(
                    f"UPDATE sync_file SET {sql} WHERE source_id=? AND path=?",
                    (*updates.values(), source_id, path),
                )
        self.conn.commit()
        row = self.get_sync_file(source_id, path)
        if row is None:
            raise RuntimeError(f"sync file was not created: {path}")
        return row

    def record_ingest_event(
        self,
        *,
        source_id: Optional[int],
        batch_id: Optional[int],
        upstream_id: Optional[str],
        event_kind: str,
        payload_hash: Optional[str],
        status: str,
        error: Optional[str] = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_event(source_id,batch_id,upstream_id,event_kind,payload_hash,received_at,status,error) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                source_id,
                batch_id,
                upstream_id,
                event_kind,
                payload_hash,
                datetime.now(timezone.utc).isoformat(),
                status,
                error,
            ),
        )
        return int(cur.lastrowid)

    def sync_status(self) -> dict[str, Any]:
        return {
            "sources": [dict(row) for row in self.rows("SELECT * FROM sync_source ORDER BY name")],
            "files": [dict(row) for row in self.rows("SELECT * FROM sync_file ORDER BY source_id,path")],
            "recent_batches": [
                dict(row)
                for row in self.rows(
                    "SELECT * FROM import_batch WHERE source_kind<>'apple_zip' ORDER BY id DESC LIMIT 20"
                )
            ],
        }

    def update_sync_source_status(
        self, source_id: int, *, success: bool, error: Optional[str] = None, cursor: Optional[str] = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if success:
            self.conn.execute(
                "UPDATE sync_source SET last_success_at=?,last_error=NULL,last_cursor=?,updated_at=? WHERE id=?",
                (now, cursor, now, source_id),
            )
        else:
            self.conn.execute(
                "UPDATE sync_source SET last_error=?,updated_at=? WHERE id=?",
                (error, now, source_id),
            )

    def insert_workout_stat(self, workout_id: int, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO workout_statistic(workout_id,raw_type,statistic_start,statistic_end,average_value,minimum_value,maximum_value,sum_value,unit) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                workout_id,
                data.get("raw_type"),
                data.get("start"),
                data.get("end"),
                data.get("average"),
                data.get("minimum"),
                data.get("maximum"),
                data.get("sum"),
                data.get("unit"),
            ),
        )

    def insert_workout_event(self, workout_id: int, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO workout_event(workout_id,event_type,event_date,duration_seconds,metadata_json) VALUES(?,?,?,?,?)",
            (
                workout_id,
                data.get("type"),
                data.get("date"),
                data.get("duration"),
                _json(data.get("metadata", {})),
            ),
        )

    def insert_activity_summary(self, batch_id: int, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO activity_summary(import_batch_id,summary_date,active_energy,active_energy_goal,exercise_minutes,exercise_minutes_goal,stand_hours,stand_hours_goal) VALUES(?,?,?,?,?,?,?,?)",
            (
                batch_id,
                data.get("date"),
                data.get("active_energy"),
                data.get("active_energy_goal"),
                data.get("exercise_minutes"),
                data.get("exercise_minutes_goal"),
                data.get("stand_hours"),
                data.get("stand_hours_goal"),
            ),
        )

    def insert_cycle_event(self, batch_id: int, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cycle_event(fingerprint,event_date,canonical_type,category_value,intensity,source,confirmed,notes,import_batch_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                data.get("fingerprint"),
                data.get("local_date"),
                data.get("canonical_type"),
                data.get("category_value"),
                None,
                data.get("source_name"),
                1,
                "",
                batch_id,
            ),
        )

    def insert_many_commit(self) -> None:
        self.conn.commit()

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, args).fetchall())

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchone()

    def count(self, table: str) -> int:
        if table not in {
            "health_sample",
            "workout",
            "strength_session",
            "strength_set",
            "nutrition_day",
            "body_measurement",
            "subjective_log",
            "cycle_event",
        }:
            raise ValueError(table)
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def insert_external(self, table: str, data: dict[str, Any], columns: Iterable[str]) -> bool:
        cols = list(columns)
        values = [data.get(c) for c in cols]
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO {table}({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            values,
        )
        self.conn.commit()
        return cur.rowcount == 1

    # The methods below are deliberately separate from ``insert_external``.  A
    # manually logged strength session is a parent record with several child
    # sets, so the complete write must be atomic and idempotent.
    def create_strength_session(
        self,
        *,
        session_date: str,
        started_at: Optional[str] = None,
        name: str = "",
        source: str = "manual",
        notes: str = "",
        fingerprint: Optional[str] = None,
        commit: bool = True,
    ) -> tuple[int, bool]:
        fingerprint = fingerprint or stable_fingerprint(
            [session_date, started_at or "", name.strip(), source.strip(), notes.strip()]
        )
        before = self.conn.total_changes
        self.conn.execute(
            "INSERT OR IGNORE INTO strength_session(fingerprint,session_date,started_at,name,source,notes) "
            "VALUES(?,?,?,?,?,?)",
            (
                fingerprint,
                session_date,
                started_at or session_date,
                name.strip(),
                source.strip(),
                notes.strip(),
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM strength_session WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if row is None:
            raise RuntimeError("strength session was not created")
        if commit:
            self.conn.commit()
        return int(row[0]), self.conn.total_changes > before

    def insert_strength_set(
        self,
        session_id: int,
        data: dict[str, Any],
        *,
        fingerprint: Optional[str] = None,
        commit: bool = True,
    ) -> tuple[int, bool]:
        def _float_or_none(value: Any) -> Optional[float]:
            return None if value is None or value == "" else float(value)

        fields = {
            "set_date": data.get("set_date"),
            "started_at": data.get("started_at") or data.get("set_date"),
            "exercise_id": data.get("exercise_id") or data.get("exercise_name"),
            "exercise_name": data.get("exercise_name"),
            "equipment": data.get("equipment") or "",
            "variation": data.get("variation") or "",
            "side": data.get("side") or "",
            "set_number": int(data["set_number"]) if data.get("set_number") is not None else None,
            "weight_kg": _float_or_none(data.get("weight_kg")),
            "reps": int(data["reps"]) if data.get("reps") is not None else None,
            "rir": _float_or_none(data.get("rir")),
            "rpe": _float_or_none(data.get("rpe")),
            "warmup": int(bool(data.get("warmup"))),
            "range_of_motion": data.get("range_of_motion") or "",
            "notes": data.get("notes") or "",
            "import_batch_id": data.get("import_batch_id"),
        }
        fingerprint = fingerprint or stable_fingerprint(
            [session_id]
            + [
                fields[key]
                for key in (
                    "set_date",
                    "started_at",
                    "exercise_name",
                    "equipment",
                    "variation",
                    "side",
                    "set_number",
                    "weight_kg",
                    "reps",
                    "rir",
                    "rpe",
                    "warmup",
                    "range_of_motion",
                    "notes",
                )
            ]
        )
        before = self.conn.total_changes
        cols = ["fingerprint", "session_id", *fields.keys()]
        values = [fingerprint, session_id, *fields.values()]
        self.conn.execute(
            f"INSERT OR IGNORE INTO strength_set({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            values,
        )
        row = self.conn.execute(
            "SELECT id FROM strength_set WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if row is None:
            raise RuntimeError("strength set was not created")
        if commit:
            self.conn.commit()
        return int(row[0]), self.conn.total_changes > before

    def save_strength_session(
        self,
        session: dict[str, Any],
        sets: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Insert one session and all sets in a single transaction."""
        # A session fingerprint must include its child sets.  Using only the
        # date/name would merge two same-day sessions (for example a morning
        # push workout and an evening pull workout) and silently attach the
        # second session's sets to the first one.  Materializing this small
        # form payload is safe and keeps repeated submissions idempotent while
        # allowing distinct same-day sessions.
        normalized_sets = list(sets)
        session_data = dict(session)
        if not session_data.get("fingerprint"):
            session_data["fingerprint"] = stable_fingerprint(
                [
                    session_data.get("session_date"),
                    session_data.get("started_at") or "",
                    session_data.get("name", "").strip(),
                    session_data.get("source", "manual").strip(),
                    session_data.get("notes", "").strip(),
                    [
                        {
                            key: item.get(key)
                            for key in (
                                "set_date",
                                "started_at",
                                "exercise_name",
                                "equipment",
                                "variation",
                                "side",
                                "set_number",
                                "weight_kg",
                                "reps",
                                "rir",
                                "rpe",
                                "warmup",
                                "range_of_motion",
                                "notes",
                            )
                        }
                        for item in normalized_sets
                    ],
                ]
            )
        with self.transaction():
            session_id, session_inserted = self.create_strength_session(
                **session_data, commit=False
            )
            inserted = 0
            set_ids: list[int] = []
            for item in normalized_sets:
                set_id, was_inserted = self.insert_strength_set(session_id, item, commit=False)
                set_ids.append(set_id)
                inserted += int(was_inserted)
        return {
            "session_id": session_id,
            "session_inserted": session_inserted,
            "sets_inserted": inserted,
            "set_ids": set_ids,
        }

    def append_strength_set(
        self,
        *,
        session_key: str,
        session_date: str,
        started_at: str = "",
        name: str = "手机快速记录",
        notes: str = "",
        data: dict[str, Any],
        force_next: bool = True,
    ) -> dict[str, Any]:
        """Append one mobile set to a stable session, idempotently."""
        session_fingerprint = stable_fingerprint(["quick_strength_session", session_key])
        with self.transaction():
            session_id, session_inserted = self.create_strength_session(
                session_date=session_date,
                started_at=started_at or session_date,
                name=name,
                source="mobile_quick",
                notes=notes,
                fingerprint=session_fingerprint,
                commit=False,
            )
            next_number = self.one(
                "SELECT COALESCE(MAX(set_number),0)+1 AS next_number FROM strength_set WHERE session_id=?",
                (session_id,),
            )["next_number"]
            item = dict(data)
            item["set_number"] = int(next_number if force_next else (item.get("set_number") or next_number))
            set_id, inserted = self.insert_strength_set(session_id, item, commit=False)
        return {
            "session_id": session_id,
            "session_inserted": session_inserted,
            "set_id": set_id,
            "set_inserted": inserted,
            "set_number": item["set_number"],
        }

    def list_strength_sessions(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.rows(
            "SELECT s.*, COUNT(t.id) AS set_count "
            "FROM strength_session s LEFT JOIN strength_set t ON t.session_id=s.id "
            "GROUP BY s.id ORDER BY COALESCE(s.started_at,s.session_date) DESC, s.id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )

    def list_strength_sets(self, session_id: int) -> list[sqlite3.Row]:
        return self.rows(
            "SELECT * FROM strength_set WHERE session_id=? ORDER BY set_number, id",
            (int(session_id),),
        )

    def update_strength_session(
        self, session_id: int, *, session_date: str, started_at: str, name: str, notes: str
    ) -> None:
        from datetime import date

        try:
            date.fromisoformat(str(session_date))
        except ValueError as exc:
            raise ValueError("训练日期必须是 YYYY-MM-DD") from exc
        old = self.one("SELECT session_date FROM strength_session WHERE id=?", (int(session_id),))
        if old is None:
            raise ValueError("训练记录不存在")
        self.conn.execute(
            "UPDATE strength_session SET session_date=?,started_at=?,name=?,notes=? WHERE id=?",
            (session_date, started_at, name.strip(), notes.strip(), int(session_id)),
        )
        if old["session_date"] != session_date:
            # Keep the parent session date and its child rows aligned so that
            # period analysis does not silently use a stale set date.
            self.conn.execute(
                "UPDATE strength_set SET set_date=? WHERE session_id=?",
                (session_date, int(session_id)),
            )
        self.conn.commit()

    def delete_strength_session(self, session_id: int) -> int:
        """Delete a manually logged session and its sets atomically."""
        with self.transaction():
            self.conn.execute("DELETE FROM strength_set WHERE session_id=?", (int(session_id),))
            cur = self.conn.execute("DELETE FROM strength_session WHERE id=?", (int(session_id),))
        return int(cur.rowcount)
