"""Explicit, replayable public wger snapshots. Never reads private training data."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ENDPOINTS = (
    "exerciseinfo",
    "exercise-translation",
    "exerciseimage",
    "video",
    "language",
    "license",
    "equipment",
    "muscle",
    "exercisecategory",
)
BASE_URL = "https://wger.de/api/v2/"


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else encoded(value).encode()
    ).hexdigest()


def migrate_catalog(conn):
    """DDL participates in Repository's migration transaction; no schema counter here."""
    statements = (
        "CREATE TABLE IF NOT EXISTS catalog_snapshot(snapshot_id TEXT PRIMARY KEY,provider TEXT NOT NULL,status TEXT NOT NULL,manifest_json TEXT NOT NULL,raw_root TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,previous_snapshot_id TEXT,published_at TEXT)",
        "CREATE TABLE IF NOT EXISTS catalog_source_record(provider TEXT NOT NULL,source_uuid TEXT NOT NULL,snapshot_id TEXT NOT NULL,source_id INTEGER,raw_sha256 TEXT NOT NULL,raw_path TEXT NOT NULL,record_json TEXT NOT NULL,PRIMARY KEY(provider,source_uuid,snapshot_id))",
        "CREATE TABLE IF NOT EXISTS catalog_source_mapping(provider TEXT NOT NULL,source_uuid TEXT NOT NULL,local_exercise_id TEXT NOT NULL,relation TEXT NOT NULL,status TEXT NOT NULL,evidence_json TEXT NOT NULL,PRIMARY KEY(provider,source_uuid,local_exercise_id))",
        "CREATE TABLE IF NOT EXISTS catalog_localization(local_exercise_id TEXT NOT NULL,locale TEXT NOT NULL,translation_version INTEGER NOT NULL,origin TEXT NOT NULL,review_status TEXT NOT NULL,content_hash TEXT NOT NULL,content_json TEXT NOT NULL,PRIMARY KEY(local_exercise_id,locale,translation_version))",
        "CREATE TABLE IF NOT EXISTS catalog_presentation(local_exercise_id TEXT NOT NULL,presentation_version INTEGER NOT NULL,snapshot_id TEXT NOT NULL,content_hash TEXT NOT NULL,content_json TEXT NOT NULL,is_current INTEGER NOT NULL,PRIMARY KEY(local_exercise_id,presentation_version))",
        "CREATE UNIQUE INDEX IF NOT EXISTS catalog_current_presentation ON catalog_presentation(local_exercise_id) WHERE is_current=1",
        "CREATE TABLE IF NOT EXISTS catalog_media(media_id TEXT PRIMARY KEY,source_uuid TEXT NOT NULL,snapshot_id TEXT NOT NULL,media_type TEXT NOT NULL,metadata_json TEXT NOT NULL,license_allowed INTEGER NOT NULL,fetch_status TEXT NOT NULL,blob_hash TEXT,local_path TEXT,verified_at TEXT,error TEXT)",
    )
    for statement in statements:
        conn.execute(statement)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(training_session_exercise)")}
    if "definition_snapshot_json" not in cols:
        conn.execute(
            "ALTER TABLE training_session_exercise ADD COLUMN definition_snapshot_json TEXT"
        )
        # Existing events remain unchanged. Freeze the recoverable definition once.
        conn.execute(
            "UPDATE training_session_exercise SET definition_snapshot_json=(SELECT definition_json FROM exercise_catalog c WHERE c.exercise_id=catalog_id AND c.definition_version=training_session_exercise.definition_version)"
        )


def fetch_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "wger.de":
        raise ValueError("目录分页仅允许官方 HTTPS 地址")
    request = urllib.request.Request(
        url, headers={"User-Agent": "HealthZIP-public-catalog/1.4", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(), response.status


def fetch_snapshot(root, *, fetcher=fetch_url):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    folder = root / ("wger-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    folder.mkdir()
    manifest = {
        "schema_version": "healthzip.catalog.snapshot/1",
        "provider": "wger",
        "api_version": "v2",
        "fetched_at": now(),
        "status": "staged",
        "endpoints": {},
    }

    def endpoint(name):
        url, seen, rows, pages, count = BASE_URL + name + "/?limit=100", set(), [], [], None
        while url:
            if url in seen:
                raise ValueError("重复分页链接: " + name)
            seen.add(url)
            raw, status = fetcher(url)
            if status != 200:
                raise ValueError(f"HTTP {status}: {url}")
            value = json.loads(raw)
            if count is None:
                count = value["count"]
            elif value["count"] != count:
                raise ValueError("分页期间上游数量变化，请重新抓取")
            filename = f"{name}-{len(pages):04d}.json"
            (folder / filename).write_bytes(raw)
            pages.append(
                {
                    "url": url,
                    "received_at": now(),
                    "http_status": status,
                    "sha256": digest(raw),
                    "path": filename,
                    "next": value.get("next"),
                    "records": len(value["results"]),
                }
            )
            rows.extend(value["results"])
            url = value.get("next")
        unique = len({r["id"] for r in rows})
        if unique != count or unique != len(rows):
            raise ValueError(f"分页缺失或重复: {name}: {len(rows)}/{unique}/{count}")
        return name, {"upstream_count": count, "unique_count": unique, "pages": pages}

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for name, meta in pool.map(endpoint, ENDPOINTS):
                manifest["endpoints"][name] = meta
        manifest["snapshot_id"] = "wger." + digest(
            {
                name: [p["sha256"] for p in value["pages"]]
                for name, value in manifest["endpoints"].items()
            }
        )
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"], manifest["error"] = "failed", str(exc)
        (folder / "manifest.json").write_text(encoded(manifest))
        raise
    (folder / "manifest.json").write_text(encoded(manifest))
    validate_snapshot(folder)
    return folder


def validate_snapshot(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["status"] != "complete" or set(manifest["endpoints"]) != set(ENDPOINTS):
        raise ValueError("不完整的目录快照不能发布")
    expected_id = "wger." + digest(
        {
            name: [page["sha256"] for page in endpoint["pages"]]
            for name, endpoint in manifest["endpoints"].items()
        }
    )
    if manifest["snapshot_id"] != expected_id:
        raise ValueError("快照身份与分页哈希不符")
    objects = {}
    for name, endpoint in manifest["endpoints"].items():
        rows, previous_next = [], None
        for index, page in enumerate(endpoint["pages"]):
            path = (folder / page["path"]).resolve()
            if path.parent != folder.resolve():
                raise ValueError("快照页路径越界")
            raw = path.read_bytes()
            if digest(raw) != page["sha256"]:
                raise ValueError("目录页哈希不符")
            value = json.loads(raw)
            if index and previous_next != page["url"]:
                raise ValueError("分页链不连续")
            previous_next = value.get("next")
            rows.extend(value["results"])
        if (
            previous_next
            or len(rows) != endpoint["upstream_count"]
            or len({r["id"] for r in rows}) != len(rows)
        ):
            raise ValueError("分页未完成或实体重复")
        objects[name] = rows
    exercises = {x["id"] for x in objects["exerciseinfo"]}
    uuids = [x.get("uuid") or f"id:{x['id']}" for x in objects["exerciseinfo"]]
    if len(set(uuids)) != len(uuids):
        raise ValueError("动作UUID重复")
    languages = {x["id"] for x in objects["language"]}
    for name in ("exercise-translation", "exerciseimage", "video"):
        if any(x["exercise"] not in exercises for x in objects[name]):
            raise ValueError("上游动作外键缺失: " + name)
    if any(x["language"] not in languages for x in objects["exercise-translation"]):
        raise ValueError("上游语言外键缺失")
    return manifest, objects


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"li", "p", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = _Text()
    parser.feed(value or "")
    return "".join(parser.parts).strip()


@lru_cache(maxsize=1)
def name_drafts():
    path = Path(__file__).with_name("catalog_name_drafts.json")
    return json.loads(path.read_text())["names"] if path.exists() else {}


EQUIPMENT = {
    "Barbell": "barbell",
    "Dumbbell": "dumbbell",
    "Kettlebell": "kettlebell",
    "Cable machine": "cable",
    "Resistance band": "elastic_band",
    "Gym mat": "bodyweight",
    "none (bodyweight exercise)": "bodyweight",
    "Pull-up bar": "bodyweight",
    "SZ-Bar": "ez_bar",
}
SUPPORT = {"Bench", "Incline bench", "Gym mat"}
REGIONS = {
    "Abs": "core",
    "Arms": "arms",
    "Back": "back",
    "Calves": "calves",
    "Chest": "chest",
    "Legs": "legs",
    "Shoulders": "shoulders",
    "Cardio": "whole_body",
}


def normalized(row, objects, snapshot_id):
    from .catalog_terms import translate_name

    languages = {x["id"]: x["short_name"] for x in objects["language"]}
    translations = row.get("translations", [])
    english = next(
        (x for x in translations if languages.get(x["language"]) == "en"),
        translations[0] if translations else {},
    )
    chinese = next(
        (x for x in translations if languages.get(x["language"], "").startswith("zh")), None
    )
    name_en = plain(english.get("name")) or f"wger {row['id']}"
    draft, unresolved = translate_name(name_en)
    source_uuid = row.get("uuid") or f"id:{row['id']}"
    explicit_draft = name_drafts().get(name_en)
    if explicit_draft and explicit_draft["source_uuid"] == source_uuid:
        draft, unresolved = explicit_draft["text"], []
    equipment = [x["name"] for x in row.get("equipment", []) if x["name"] not in SUPPORT]
    category = EQUIPMENT.get(equipment[0], "other") if len(equipment) == 1 else "other"
    names = {
        "en": {"text": name_en, "origin": "upstream"},
        "zh-CN": {
            "text": plain(chinese["name"]) if chinese else draft,
            "origin": "upstream" if chinese else "project_translation",
            "review_status": "upstream_unreviewed" if chinese else "draft",
            "untranslated_terms": [] if chinese else unresolved,
        },
    }
    return {
        "exercise_id": "catalog.wger." + source_uuid,
        "definition_version": 1,
        "name_zh": names["zh-CN"]["text"],
        "name_en": name_en,
        "names": names,
        "aliases_zh": list(
            dict.fromkeys(
                [
                    plain(x["name"])
                    for x in translations
                    if languages.get(x["language"]) in {"en", "zh", "zh-cn"}
                ]
                + [plain(a["alias"]) for x in translations for a in x.get("aliases", [])]
            )
        ),
        "description": plain((chinese or english).get("description")),
        "description_language": languages.get((chinese or english).get("language"), "unknown"),
        "recording_mode": "unknown",
        "mode_basis": "requires_user_confirmation",
        "equipment_type": category,
        "default_load_basis": "unknown",
        "requires_load_basis_confirmation": True,
        "display_regions": [REGIONS.get(row.get("category", {}).get("name"), "other")],
        "movement_patterns": [],
        "source": {
            "provider": "wger",
            "source_id": row["id"],
            "source_uuid": source_uuid,
            "snapshot_id": snapshot_id,
            "raw_sha256": digest(row),
            "source_updated_at": row.get("last_update_global"),
            "license": row.get("license"),
            "authors": row.get("author_history", []),
        },
        "upstream_equipment": row.get("equipment", []),
        "source_variation_group": row.get("variation_group"),
        "upstream_muscle_tags": {
            "primary": row.get("muscles", []),
            "secondary": row.get("muscles_secondary", []),
            "use": "navigation",
        },
        "reviewed_anatomy": None,
        "scientific_review": {"status": "unreviewed", "source_ids": []},
        "muscle_participation_proposals": [],
        "status": "public_catalog",
    }


def presentation(conn, exercise_id):
    row = conn.execute(
        "SELECT content_json,presentation_version FROM catalog_presentation WHERE local_exercise_id=? AND is_current=1",
        (exercise_id,),
    ).fetchone()
    return (
        {**json.loads(row["content_json"]), "presentation_version": row["presentation_version"]}
        if row
        else {}
    )


def published_snapshot(conn):
    row = conn.execute(
        "SELECT snapshot_id FROM catalog_snapshot WHERE status='published' ORDER BY published_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def mapping_continuity(conn, mapping, raw):
    """Keep an exact identity only while its original reviewed evidence still agrees.

    Other-language labels, aliases, media and timestamps are presentation data.
    The name in the reviewed language can identify a physical variant and must
    remain unchanged alongside its description. The stored, hashed
    source record remains the comparison baseline; a sequence of small updates
    must not gradually replace the evidence that was actually reviewed.
    """
    if not raw:
        return None
    evidence = mapping["evidence"]
    reviewed_hash = evidence["source_record_sha256"]
    current_hash = digest(raw)
    if current_hash == reviewed_hash:
        return {"basis": "exact_reviewed_record", "source_record_sha256": current_hash}
    if mapping["status"] != "confirmed" or mapping["relation"] != "exact_identity":
        return None
    locator = re.fullmatch(r"exerciseinfo/(\d+)/translations/language=(\d+)", evidence["locator"])
    if not locator or raw["id"] != int(locator[1]):
        return None
    row = conn.execute(
        "SELECT record_json FROM catalog_source_record WHERE provider='wger' "
        "AND source_uuid=? AND raw_sha256=? LIMIT 1",
        (mapping["source_uuid"], reviewed_hash),
    ).fetchone()
    if not row:
        return None
    reviewed = json.loads(row[0])
    if digest(reviewed) != reviewed_hash:
        return None

    def identity(record):
        translations = [
            item
            for item in record.get("translations", [])
            if item.get("language") == int(locator[2])
        ]
        if len(translations) != 1:
            return None
        return {
            "record": {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "created",
                    "last_update",
                    "last_update_global",
                    "images",
                    "videos",
                    "translations",
                    "author_history",
                    "total_authors_history",
                }
            },
            "identity_translation": {
                key: value
                for key, value in translations[0].items()
                if key not in {"aliases", "created", "author_history"}
            },
        }

    before, after = identity(reviewed), identity(raw)
    if before is None or before != after:
        return None
    return {
        "basis": "unchanged_reviewed_identity_evidence",
        "reviewed_source_record_sha256": reviewed_hash,
        "current_source_record_sha256": current_hash,
        "identity_projection_sha256": digest(before),
        "locator": evidence["locator"],
    }


def publish_snapshot(repo, folder):
    from .catalog_media import media_metadata
    from .service import TrainingService

    manifest, objects = validate_snapshot(folder)
    svc = TrainingService(repo)
    sid = manifest["snapshot_id"]
    existing = repo.conn.execute(
        "SELECT status FROM catalog_snapshot WHERE snapshot_id=?", (sid,)
    ).fetchone()
    old = published_snapshot(repo.conn)
    if existing and old == sid:
        old = repo.conn.execute(
            "SELECT previous_snapshot_id FROM catalog_snapshot WHERE snapshot_id=?", (sid,)
        ).fetchone()[0]
    definitions = [normalized(row, objects, sid) for row in objects["exerciseinfo"]]
    local_ids = set()
    source_paths = {}
    for page in manifest["endpoints"]["exerciseinfo"]["pages"]:
        for raw in json.loads((Path(folder) / page["path"]).read_text())["results"]:
            source_paths[raw["id"]] = page["path"]
    with svc._transaction():
        repo.conn.execute(
            "INSERT OR REPLACE INTO catalog_snapshot VALUES(?,?,?,?,?,?,?,?)",
            (
                sid,
                "wger",
                "complete",
                encoded(manifest),
                str(Path(folder).resolve()),
                digest(manifest),
                old,
                None,
            ),
        )
        mapping_path = Path(__file__).with_name("catalog_legacy_mapping.json")
        source_by_uuid = {r.get("uuid"): r for r in objects["exerciseinfo"]}
        for mapping in (
            json.loads(mapping_path.read_text())["mappings"] if mapping_path.exists() else []
        ):
            if not mapping["source_uuid"]:
                continue
            raw = source_by_uuid.get(mapping["source_uuid"])
            continuity = mapping_continuity(repo.conn, mapping, raw)
            status = mapping["status"] if continuity else "needs_identity_review"
            repo.conn.execute(
                "INSERT OR REPLACE INTO catalog_source_mapping VALUES('wger',?,?,?,?,?)",
                (
                    mapping["source_uuid"],
                    mapping["local_exercise_id"],
                    mapping["relation"],
                    status,
                    encoded({**mapping, "current_evidence_check": continuity}),
                ),
            )
        for raw, item in zip(objects["exerciseinfo"], definitions):
            uuid = item["source"]["source_uuid"]
            exact = repo.conn.execute(
                "SELECT local_exercise_id FROM catalog_source_mapping WHERE provider='wger' AND source_uuid=? AND relation='exact_identity' AND status='confirmed' ORDER BY local_exercise_id LIKE 'psa.ex.%' DESC",
                (uuid,),
            ).fetchone()
            if exact:
                item["exercise_id"] = exact[0]
            eid = item["exercise_id"]
            local_ids.add(eid)
            previous = repo.conn.execute(
                "SELECT * FROM exercise_catalog WHERE exercise_id=? ORDER BY definition_version DESC LIMIT 1",
                (eid,),
            ).fetchone()
            if previous:
                previous_definition = json.loads(previous["definition_json"])
                item["definition_version"] = previous["definition_version"]
                # Only source semantic changes create a new definition, never labels/media.
                changed = (
                    any(
                        item.get(k) != previous_definition.get(k)
                        for k in (
                            "upstream_equipment",
                            "source_variation_group",
                            "equipment_type",
                            "recording_mode",
                            "default_load_basis",
                        )
                    )
                    if not eid.startswith("psa.ex.")
                    else False
                )
                if changed:
                    item["definition_version"] += 1
            if eid.startswith("psa.ex."):
                item["name_zh"] = previous_definition["name_zh"]
                item["names"]["zh-CN"] = {
                    "text": item["name_zh"],
                    "origin": "project_seed",
                    "review_status": "existing_project_label",
                }
                repo.conn.execute(
                    "UPDATE exercise_catalog SET active=0 WHERE exercise_id=?",
                    ("catalog.wger." + uuid,),
                )
            repo.conn.execute(
                "INSERT OR IGNORE INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,active,created_at) VALUES(?,?,'public',?,?,0,1,?)",
                (eid, item["definition_version"], item["name_zh"], encoded(item), now()),
            )
            repo.conn.execute("UPDATE exercise_catalog SET active=1 WHERE exercise_id=?", (eid,))
            previous_p = presentation(repo.conn, eid)
            content = {
                k: item[k]
                for k in (
                    "name_zh",
                    "name_en",
                    "names",
                    "aliases_zh",
                    "description",
                    "description_language",
                    "source",
                    "upstream_muscle_tags",
                    "reviewed_anatomy",
                    "display_regions",
                )
            }
            # Snapshot identity is audit metadata, not a reason to duplicate labels.
            old_content = {k: previous_p.get(k) for k in content}
            if previous_p and old_content.get("source"):
                old_content["source"] = {**old_content["source"], "snapshot_id": sid}
            if not previous_p or digest(old_content) != digest(content):
                version = previous_p.get("presentation_version", 0) + 1
                repo.conn.execute(
                    "UPDATE catalog_presentation SET is_current=0 WHERE local_exercise_id=?", (eid,)
                )
                repo.conn.execute(
                    "INSERT INTO catalog_presentation VALUES(?,?,?,?,?,1)",
                    (eid, version, sid, digest(content), encoded(content)),
                )
                zh = content["names"]["zh-CN"]
                repo.conn.execute(
                    "INSERT INTO catalog_localization VALUES(?, 'zh-CN',?,?,?,?,?)",
                    (eid, version, zh["origin"], zh["review_status"], digest(zh), encoded(zh)),
                )
            repo.conn.execute(
                "INSERT OR IGNORE INTO catalog_source_record VALUES('wger',?,?,?,?,?,?)",
                (uuid, sid, raw["id"], digest(raw), source_paths[raw["id"]], encoded(raw)),
            )
            for reused in repo.conn.execute(
                "SELECT DISTINCT source_uuid FROM catalog_source_record WHERE provider='wger' AND source_id=? AND source_uuid<>?",
                (raw["id"], uuid),
            ).fetchall():
                repo.conn.execute(
                    "INSERT OR IGNORE INTO catalog_source_mapping VALUES('wger',?,?,'possible_duplicate','source_id_reused',?)",
                    (
                        uuid,
                        "catalog.wger." + reused[0],
                        encoded(
                            {
                                "reason": "source_integer_id_reused_with_different_uuid",
                                "snapshot_id": sid,
                            }
                        ),
                    ),
                )
            repo.conn.execute(
                "INSERT OR IGNORE INTO catalog_source_mapping VALUES('wger',?,?,'exact_identity','confirmed',?)",
                (
                    uuid,
                    eid,
                    encoded(
                        {
                            "basis": "source_uuid",
                            "identity_review": "source_identity_only",
                            "created_at": now(),
                        }
                    ),
                ),
            )
        current_uuids = {item["source"]["source_uuid"] for item in definitions}
        for row in repo.conn.execute(
            "SELECT DISTINCT local_exercise_id,source_uuid FROM catalog_source_mapping WHERE provider='wger'"
        ).fetchall():
            if row["source_uuid"] not in current_uuids and row["local_exercise_id"].startswith(
                "catalog.wger."
            ):
                repo.conn.execute(
                    "UPDATE exercise_catalog SET active=0 WHERE exercise_id=?",
                    (row["local_exercise_id"],),
                )
        media_ids = set()
        for kind, endpoint in (("image", "exerciseimage"), ("video", "video")):
            for raw in objects[endpoint]:
                meta, allowed = media_metadata(raw, kind, objects["license"])
                mid = meta["media_id"]
                media_ids.add(mid)
                prior = repo.conn.execute(
                    "SELECT * FROM catalog_media WHERE media_id=?", (mid,)
                ).fetchone()
                same = (
                    prior
                    and {
                        k: v
                        for k, v in json.loads(prior["metadata_json"]).items()
                        if k != "verified_file"
                    }
                    == meta
                    and prior["license_allowed"] == allowed
                )
                if same and json.loads(prior["metadata_json"]).get("verified_file"):
                    meta["verified_file"] = json.loads(prior["metadata_json"])["verified_file"]
                status = (
                    prior["fetch_status"] if same else ("pending" if allowed else "license_unknown")
                )
                repo.conn.execute(
                    "INSERT OR REPLACE INTO catalog_media VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        mid,
                        meta["source_uuid"],
                        sid,
                        kind,
                        encoded(meta),
                        int(allowed),
                        status,
                        prior["blob_hash"] if same else None,
                        prior["local_path"] if same else None,
                        prior["verified_at"] if same else None,
                        None,
                    ),
                )
        for row in repo.conn.execute("SELECT media_id FROM catalog_media").fetchall():
            if row[0] not in media_ids:
                repo.conn.execute(
                    "UPDATE catalog_media SET fetch_status='withdrawn',license_allowed=0 WHERE media_id=?",
                    (row[0],),
                )
        repo.conn.execute("UPDATE catalog_snapshot SET status='complete' WHERE status='published'")
        repo.conn.execute(
            "UPDATE catalog_snapshot SET status='published',published_at=? WHERE snapshot_id=?",
            (now(), sid),
        )
        repo.conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES('catalog_data_version','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
        )
    return coverage(repo)


def public_catalog(repo):
    # Explicit projection excludes favorites, private aliases, equipment and sessions.
    items = []
    allowed = {
        "exercise_id",
        "definition_version",
        "presentation_version",
        "name_zh",
        "name_en",
        "names",
        "recording_mode",
        "mode_basis",
        "equipment_type",
        "default_load_basis",
        "requires_load_basis_confirmation",
        "display_regions",
        "aliases_zh",
        "movement_patterns",
        "description",
        "description_language",
        "source",
        "upstream_equipment",
        "source_variation_group",
        "upstream_muscle_tags",
        "reviewed_anatomy",
        "scientific_review",
        "muscle_participation_proposals",
        "status",
    }
    for row in repo.conn.execute(
        "SELECT c.* FROM exercise_catalog c WHERE owner_id='public' AND active=1 AND definition_version=(SELECT MAX(definition_version) FROM exercise_catalog x WHERE x.exercise_id=c.exercise_id)"
    ):
        item = json.loads(row["definition_json"])
        if item.get("import_origin") == "external_public_definition_unverified":
            continue
        item.update(presentation(repo.conn, row["exercise_id"]))
        item = {key: value for key, value in item.items() if key in allowed}
        item["name"] = item.get("name_zh", row["name"])
        items.append(item)
    return {
        "format": "healthzip.public_catalog/1",
        "snapshot_id": published_snapshot(repo.conn),
        "items": items,
    }


def coverage(repo):
    public = public_catalog(repo)
    items = public["items"]
    source = [x for x in items if x.get("source", {}).get("provider") == "wger"]
    media = [
        dict(x)
        for x in repo.conn.execute(
            "SELECT media_type,fetch_status,COUNT(*) AS count,COUNT(DISTINCT source_uuid) AS actions FROM catalog_media GROUP BY media_type,fetch_status"
        )
    ]
    manifest_row = repo.conn.execute(
        "SELECT manifest_json FROM catalog_snapshot WHERE snapshot_id=?", (public["snapshot_id"],)
    ).fetchone()
    manifest = json.loads(manifest_row[0]) if manifest_row else {}
    counts = {
        name: endpoint["unique_count"] for name, endpoint in manifest.get("endpoints", {}).items()
    }
    totals = [
        dict(x)
        for x in repo.conn.execute(
            "SELECT media_type,COUNT(*) AS objects,COUNT(DISTINCT source_uuid) AS actions FROM catalog_media WHERE fetch_status!='withdrawn' GROUP BY media_type"
        )
    ]
    return {
        "snapshot_id": public["snapshot_id"],
        "source_counts": counts,
        "public_exercises": len(items),
        "wger_exercises": len(source),
        "zh_upstream": sum(
            x.get("names", {}).get("zh-CN", {}).get("origin") == "upstream" for x in source
        ),
        "zh_project_seed": sum(
            x.get("names", {}).get("zh-CN", {}).get("origin") == "project_seed" for x in source
        ),
        "zh_drafts": sum(
            x.get("names", {}).get("zh-CN", {}).get("origin") == "project_translation"
            for x in source
        ),
        "zh_drafts_with_untranslated_terms": sum(
            bool(x.get("names", {}).get("zh-CN", {}).get("untranslated_terms")) for x in source
        ),
        "reviewed_anatomy": 0,
        "media": media,
        "media_totals": totals,
    }


def diff_snapshots(old, new):
    _, before = validate_snapshot(old)
    _, after = validate_snapshot(new)
    a = {r.get("uuid") or f"id:{r['id']}": r for r in before["exerciseinfo"]}
    b = {r.get("uuid") or f"id:{r['id']}": r for r in after["exerciseinfo"]}
    return {
        "added": sorted(b.keys() - a.keys()),
        "removed": sorted(a.keys() - b.keys()),
        "changed": sorted(k for k in a.keys() & b.keys() if digest(a[k]) != digest(b[k])),
    }
