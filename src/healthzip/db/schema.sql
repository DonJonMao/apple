
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO schema_meta(key,value) VALUES ('schema_version','1');
CREATE TABLE IF NOT EXISTS import_batch (
 id INTEGER PRIMARY KEY, file_sha256 TEXT NOT NULL, file_name TEXT, file_size_bytes INTEGER,
 exported_at TEXT, imported_at TEXT NOT NULL, status TEXT NOT NULL, xml_member_path TEXT,
 records_seen INTEGER DEFAULT 0, records_inserted INTEGER DEFAULT 0, records_deduplicated INTEGER DEFAULT 0,
 records_skipped INTEGER DEFAULT 0, errors_count INTEGER DEFAULT 0, date_min TEXT, date_max TEXT,
 unknown_type_counts_json TEXT DEFAULT '{}', error_samples_json TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_batch_hash ON import_batch(file_sha256);
CREATE TABLE IF NOT EXISTS health_sample (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, import_batch_id INTEGER NOT NULL REFERENCES import_batch(id),
 raw_type TEXT NOT NULL, canonical_type TEXT, raw_value TEXT, raw_unit TEXT, normalized_value REAL,
 normalized_unit TEXT, unit_status TEXT, category_value TEXT, start_utc TEXT, end_utc TEXT, creation_utc TEXT,
 local_datetime TEXT, local_date TEXT, utc_offset_minutes INTEGER, source_name TEXT, source_version TEXT,
 device TEXT, metadata_json TEXT DEFAULT '{}', quality_flags_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sample_type_date ON health_sample(canonical_type, local_date);
CREATE INDEX IF NOT EXISTS idx_sample_start ON health_sample(start_utc);
CREATE TABLE IF NOT EXISTS workout (
 id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, import_batch_id INTEGER NOT NULL REFERENCES import_batch(id),
 activity_type TEXT, start_utc TEXT, end_utc TEXT, local_date TEXT, duration_seconds REAL,
 distance_value REAL, distance_unit TEXT, energy_value REAL, energy_unit TEXT, source_name TEXT, source_version TEXT,
 device TEXT, metadata_json TEXT DEFAULT '{}', suspected_duplicate INTEGER DEFAULT 0
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
