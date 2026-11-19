"""Synthetic, isolated data for the strength workbench browser acceptance.

This helper never reads the repository's .local folder. Every identity, note,
measurement and date below is a software fixture, not a user's health record.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def create_fixture(database: Path) -> dict:
    """Create >50 same-month sessions, mixed latest history and three modes."""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    first = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
    manifest = {"data": "synthetic_only", "month": first.strftime("%Y-%m")}
    with closing(Repository(database)) as repo:
        svc = TrainingService(repo)
        equipment = svc.create_equipment("合成固定杠铃架", "barbell")
        condition = {
            "equipment_instance_id": equipment["id"],
            "load_basis": "external_total_kg",
            "load_basis_confirmed": True,
            "side": "bilateral",
            "repetition_semantics": "full_repetitions",
            "rom_protocol": "synthetic-full-rom",
            "settings": {},
            "settings_confirmed": True,
        }
        distance = svc.create_exercise(
            "合成双手农夫搬运", "distance", "dumbbell", "per_dumbbell_kg",
            regions=["whole_body"], exercise_id="custom.synthetic-distance",
        )
        long_name = svc.create_exercise(
            "合成长中文名称单侧器械辅助训练动作与技术记录", "repetitions", "machine",
            "assistance_setting", regions=["back"], exercise_id="custom.synthetic-long",
        )
        scale = svc.create_exercise(
            "合成器械刻度推举", "repetitions", "machine", "machine_setting",
            regions=["shoulders"], exercise_id="custom.synthetic-scale",
        )
        # A neutral test swatch exercises the genuine local-media path. It is
        # explicitly synthetic and is never represented as an exercise demo.
        from PIL import Image

        image_path = database.parent / "synthetic-neutral-media.png"
        Image.new("RGB", (64, 64), (66, 66, 72)).save(image_path)
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        repo.conn.execute(
            "INSERT INTO catalog_source_mapping VALUES('wger','synthetic-neutral-media',?,"
            "'exact_identity','confirmed',?)",
            (long_name["exercise_id"], json.dumps({"synthetic_fixture_only": True})),
        )
        metadata = {
            "media_id": "synthetic.neutral-placeholder", "media_type": "image",
            "author": "合成占位，非动作示范", "attribution_text": "合成测试占位 · 非动作示范",
            "license": {"short_name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
            "verified_file": {"mime": "image/png"}, "changes": "synthetic solid neutral swatch",
        }
        repo.conn.execute(
            "INSERT INTO catalog_media(media_id,source_uuid,snapshot_id,media_type,metadata_json,"
            "license_allowed,fetch_status,blob_hash,local_path,verified_at) "
            "VALUES(?,'synthetic-neutral-media','synthetic-only','image',?,1,'ready',?,?,?)",
            (metadata["media_id"], json.dumps(metadata), digest, str(image_path), now.isoformat()),
        )
        repo.conn.commit()
        ids = [
            "psa.ex.barbell_bench_press", "psa.ex.dumbbell_incline_press",
            "psa.ex.dumbbell_lateral_raise", "psa.ex.plank",
            distance["exercise_id"], long_name["exercise_id"],
        ]
        # A real month inventory must not be truncated to the history page size.
        calendar_ids = []
        for index in range(61):
            at = first + timedelta(minutes=index * 5)
            session = svc.start_session(
                f"合成月历训练 {index + 1:02}", started_at=at.isoformat(),
                event_id=f"synthetic-calendar-session-{index}",
            )
            svc.end_session(session["id"], ended_at=(at + timedelta(minutes=3)).isoformat())
            calendar_ids.append(session["id"])
        deleted_session = svc.get_session(calendar_ids[-1])
        deleted = svc.delete_session(
            deleted_session["id"], base_revision=deleted_session["revision"],
            event_id="synthetic-calendar-deleted",
        )
        # Mixed weights, incomplete RIR and quality facts stay as separate rows.
        older_at = now - timedelta(days=4)
        recent_at = now - timedelta(days=2)
        history_ids = []
        latest_rows = []
        for index, at in enumerate((older_at, recent_at)):
            session = svc.start_session(
                "合成上次实际" if index else "合成更早实际", started_at=at.isoformat()
            )
            item = svc.add_exercise(session["id"], ids[0], condition)
            values = [(60, 12, 2)] if index == 0 else [(55, 10, 2), (55, 9, 0), (50, 11, None)]
            for order, (load, reps, rir) in enumerate(values):
                ended = at + timedelta(minutes=order * 3 + 1)
                row = svc.add_set(item["id"], {
                    "completion_state": "completed", "load_value": load,
                    "load_unit": "kg", "reps": reps, "rir": rir,
                    "ended_at": ended.isoformat(), "quality_status": "acceptable",
                    "pain_flag": False, "notes": "合成高级字段保留检查",
                })
                if index:
                    latest_rows.append(row["set_uuid"])
            svc.end_session(session["id"], ended_at=(at + timedelta(minutes=30)).isoformat())
            history_ids.append(session["id"])
        old_at = now - timedelta(days=480)
        old = svc.start_session("合成超过一年动作历史", started_at=old_at.isoformat())
        old_item = svc.add_exercise(old["id"], ids[1], {
            "load_basis": "per_dumbbell_kg", "load_basis_confirmed": True,
        })
        svc.add_set(old_item["id"], {
            "completion_state": "completed", "load_value": "12.5", "load_unit": "kg",
            "reps": 9, "ended_at": (old_at + timedelta(minutes=2)).isoformat(),
        })
        svc.end_session(old["id"], ended_at=(old_at + timedelta(minutes=20)).isoformat())
        # Cross-year and UTC-to-local month edge are explicit synthetic records.
        edge_at = first.astimezone(timezone.utc).replace(hour=16) - timedelta(days=1)
        edge = svc.start_session("合成时区月界", started_at=edge_at.isoformat())
        svc.end_session(edge["id"], ended_at=(edge_at + timedelta(minutes=2)).isoformat())
        year_at = datetime(now.year - 1, 12, 31, 23, 58, tzinfo=ZoneInfo("Asia/Shanghai"))
        year = svc.start_session("合成跨年记录", started_at=year_at.isoformat())
        svc.end_session(year["id"], ended_at=(year_at + timedelta(minutes=4)).isoformat())
        bases = ["external_total_kg", "per_dumbbell_kg", "per_dumbbell_kg",
                 "bodyweight_no_external", "per_dumbbell_kg", "assistance_setting"]
        template = svc.create_template("合成六动作三组计划", [{
            "exercise_id": identity,
            "condition": {"load_basis": basis, "load_basis_confirmed": True},
            "targets": {"sets": [{"set_type": "work"} for _ in range(3)]},
        } for identity, basis in zip(ids, bases)])
        manifest.update(
            catalog_ids=ids, scale_id=scale["exercise_id"],
            calendar_session_ids=calendar_ids, calendar_deleted_event=deleted["event_id"],
            latest_history_session_id=history_ids[-1], latest_history_set_uuids=latest_rows,
            old_history_session_id=old["id"], edge_session_id=edge["id"],
            year_session_id=year["id"], template_id=template["id"],
        )
    return manifest
