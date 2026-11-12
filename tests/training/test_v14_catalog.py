"""v1.4 catalog, frozen definitions and real multi-session UI regressions."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from healthzip.db.repository import Repository
from healthzip.training.catalog_import import (
    ENDPOINTS,
    digest,
    encoded,
    fetch_snapshot,
    presentation,
    public_catalog,
    publish_snapshot,
)
from healthzip.training.catalog_media import fetch_media, media_for, offline_package
from healthzip.training.offline import browser_bootstrap, recorder_html
from healthzip.training.service import TrainingService


def source(identity=101, *, name="Synthetic Row", uuid="synthetic-row", equipment="Dumbbell"):
    return {
        "id": identity,
        "uuid": uuid,
        "category": {"id": 1, "name": "Back"},
        "equipment": [{"id": 1, "name": equipment}],
        "muscles": [{"id": 1, "name": "Synthetic muscle"}],
        "muscles_secondary": [],
        "variation_group": "synthetic-variation",
        "license": {"id": 1},
        "translations": [
            {
                "id": identity + 100,
                "language": 2,
                "name": name,
                "description": "<p>Source description</p><script>do not run</script>",
                "aliases": [{"alias": "合成划船"}],
            }
        ],
    }


def snapshot(tmp_path, rows=None, *, images=None, videos=None, languages=None, suffix="first"):
    path = tmp_path / suffix
    path.mkdir()
    rows = rows if rows is not None else [source()]
    objects = {name: [] for name in ENDPOINTS}
    objects.update(
        {
            "exerciseinfo": rows,
            "exercise-translation": [
                {"id": row["id"] + 100, "exercise": row["id"], "language": 2} for row in rows
            ],
            "language": languages or [{"id": 2, "short_name": "en"}],
            "license": [
                {
                    "id": 1,
                    "url": "https://creativecommons.org/licenses/by-sa/4.0/deed.en",
                    "short_name": "CC BY-SA 4.0",
                }
            ],
            "exerciseimage": images or [],
            "video": videos or [],
        }
    )
    manifest = {
        "status": "complete",
        "provider": "wger",
        "endpoints": {},
        "fetched_at": "2026-11-11T00:00:00+00:00",
    }
    for name, records in objects.items():
        raw = encoded({"count": len(records), "next": None, "results": records}).encode()
        filename = name + ".json"
        (path / filename).write_bytes(raw)
        manifest["endpoints"][name] = {
            "upstream_count": len(records),
            "unique_count": len(records),
            "pages": [
                {
                    "path": filename,
                    "url": "https://wger.de/api/v2/" + name + "/?limit=100",
                    "sha256": digest(raw),
                }
            ],
        }
    manifest["snapshot_id"] = "wger." + digest(
        {
            name: [p["sha256"] for p in value["pages"]]
            for name, value in manifest["endpoints"].items()
        }
    )
    (path / "manifest.json").write_text(encoded(manifest))
    return path


def picture(*, license=1, uuid="synthetic-row"):
    return {
        "id": 1,
        "exercise": 101,
        "exercise_uuid": uuid,
        "image": "https://wger.de/media/synthetic.png",
        "license": license,
        "license_author": "Synthetic Test Author",
        "is_main": True,
    }


def png():
    out = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def repo(tmp_path):
    value = Repository(tmp_path / "test.sqlite3")
    yield value
    value.close()


def test_complete_snapshot_idempotence_and_incomplete_rejection(repo, tmp_path):
    folder = snapshot(tmp_path)
    first = publish_snapshot(repo, folder)
    assert first["wger_exercises"] == 1 and first["public_exercises"] == 47
    publish_snapshot(repo, folder)
    assert repo.conn.execute("SELECT COUNT(*) FROM catalog_presentation").fetchone()[0] == 1
    (folder / "exerciseinfo.json").write_text("{}")
    with pytest.raises(ValueError, match="哈希"):
        publish_snapshot(repo, folder)
    assert len(public_catalog(repo)["items"]) == 47


def test_fetch_interruption_and_repeated_page_cannot_publish(tmp_path):
    def interrupted(url):
        raise OSError("synthetic interruption")

    with pytest.raises(OSError):
        fetch_snapshot(tmp_path / "failed", fetcher=interrupted)
    failure = next((tmp_path / "failed").glob("*/manifest.json"))
    assert json.loads(failure.read_text())["status"] == "failed"

    def duplicate(url):
        return encoded({"count": 2, "results": [{"id": 1}, {"id": 1}], "next": None}).encode(), 200

    with pytest.raises(ValueError, match="重复"):
        fetch_snapshot(tmp_path / "duplicate", fetcher=duplicate)


def test_presentation_update_does_not_rewrite_history_or_definition(repo, tmp_path):
    svc = TrainingService(repo)
    custom = svc.create_exercise("原始名称", "repetitions", "dumbbell", "per_dumbbell_kg")
    session = svc.start_session("history")
    instance = svc.add_exercise(session["id"], custom["exercise_id"], {})
    svc.update_exercise(custom["exercise_id"], {"name_zh": "当前名称"}, base_revision=1)
    frozen = svc.get_session_exercise(instance["id"])
    assert frozen["exercise"]["name"] == "原始名称"
    assert frozen["condition_key"] == instance["condition_key"]
    folder = snapshot(tmp_path)
    publish_snapshot(repo, folder)
    eid = "catalog.wger.synthetic-row"
    before = svc.get_exercise(eid)
    changed = source(name="Renamed Synthetic Row")
    publish_snapshot(repo, snapshot(tmp_path, [changed], suffix="rename"))
    assert svc.get_exercise(eid)["definition_version"] == before["definition_version"]
    assert presentation(repo.conn, eid)["presentation_version"] == 2
    assert presentation(repo.conn, eid)["description"] == "Source description"


@pytest.mark.parametrize(
    "changes", [{"recording_mode": "duration"}, {"default_load_basis": "dumbbells_total_kg"}]
)
def test_f06_history_template_keeps_actual_definition(repo, changes):
    svc = TrainingService(repo)
    exercise = svc.create_exercise("版本测试", "repetitions", "dumbbell", "per_dumbbell_kg")
    session = svc.start_session("old")
    original = svc.add_exercise(
        session["id"], exercise["exercise_id"], {}, {"sets": [{"reps_min": 6, "reps_max": 8}]}
    )
    svc.update_exercise(exercise["exercise_id"], changes, base_revision=1)
    template = svc.save_session_as_template(session["id"], "保留历史")
    assert template["items"][0]["definition_version"] == 1
    recreated = svc.start_session("copy", template_id=template["id"])
    assert recreated["exercises"][0]["exercise"]["recording_mode"] == "repetitions"
    assert recreated["exercises"][0]["definition_version"] == 1
    assert (
        recreated["exercises"][0]["condition"]["load_basis"] == original["condition"]["load_basis"]
    )
    assert svc.get_exercise(exercise["exercise_id"])["definition_version"] == 2


def test_new_definition_rejects_cross_mode_targets(repo):
    svc = TrainingService(repo)
    exercise = svc.create_exercise("持续", "duration", "bodyweight", "unknown")
    with pytest.raises(ValueError, match="测量模式"):
        svc.create_template(
            "错误",
            [{"exercise_id": exercise["exercise_id"], "targets": {"sets": [{"reps_min": 6}]}}],
        )


def test_source_semantic_change_versions_definition_and_uuid_change_queues(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path))
    publish_snapshot(repo, snapshot(tmp_path, [source(equipment="Barbell")], suffix="equipment"))
    svc = TrainingService(repo)
    assert svc.get_exercise("catalog.wger.synthetic-row")["definition_version"] == 2
    assert svc.get_exercise("catalog.wger.synthetic-row", 1)["equipment_type"] == "dumbbell"
    publish_snapshot(repo, snapshot(tmp_path, [source(uuid="new-uuid")], suffix="new-uuid"))
    assert not svc.search_exercises("catalog.wger.synthetic-row")
    assert svc.get_exercise("catalog.wger.synthetic-row", 1)
    assert (
        repo.conn.execute(
            "SELECT COUNT(*) FROM catalog_source_mapping WHERE status='source_id_reused'"
        ).fetchone()[0]
        == 1
    )


def test_search_alias_english_id_pagination_and_private_export(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path))
    svc = TrainingService(repo)
    for query in ("合成划船", "Synthetic Row", "catalog.wger.synthetic-row"):
        assert (
            svc.search_catalog(query, limit=1)["items"][0]["exercise_id"]
            == "catalog.wger.synthetic-row"
        )
    svc.add_alias("catalog.wger.synthetic-row", "私人别名不公开")
    svc.favorite("catalog.wger.synthetic-row")
    svc.create_exercise("私人动作不公开", "distance", "dumbbell", "per_dumbbell_kg")
    public = encoded(public_catalog(repo))
    assert "私人别名不公开" not in public and "私人动作不公开" not in public
    assert svc.search_catalog(limit=10)["total"] == 48


def test_chinese_draft_numeric_terms_do_not_corrupt_display_names():
    from healthzip.training.catalog_terms import translate_name

    for original, expected in (
        ("2 Handed Kettlebell Swing", "双手 壶铃 摆动"),
        ("Barbell Lunges Standing", "杠铃 弓步 站姿"),
        ("Box Jumps", "跳箱"),
    ):
        draft, unresolved = translate_name(original)
        assert draft == expected and not unresolved


def test_per_object_license_cache_bytes_and_attribution(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path, images=[picture()]))
    fetch_media(repo, tmp_path / "blobs", downloader=lambda _: (png(), "image/png"))
    media = media_for(repo.conn, "catalog.wger.synthetic-row")[0]
    assert media["fetch_status"] == "ready" and Path(media["local_path"]).read_bytes() == png()
    assert media["author"] == "Synthetic Test Author" and media["verified_file"]["width"] == 3
    calls = []
    fetch_media(repo, tmp_path / "blobs", downloader=lambda u: calls.append(u))
    assert calls == []
    publish_snapshot(repo, snapshot(tmp_path, images=[picture(license=None)], suffix="rights"))
    assert media_for(repo.conn, "catalog.wger.synthetic-row")[0]["local_path"] is None
    fetch_media(repo, tmp_path / "blobs", downloader=lambda u: calls.append(u))
    assert calls == []


def test_corrupt_media_is_failed_and_no_media_is_distinct(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path, images=[picture()]))
    fetch_media(repo, tmp_path / "blobs", downloader=lambda _: (b"not an image", "image/png"))
    svc = TrainingService(repo)
    assert (
        svc.exercise_details("catalog.wger.synthetic-row")["media"][0]["fetch_status"] == "failed"
    )
    assert svc.exercise_details("psa.ex.plank")["media_availability"] == "none_in_source"


def test_catalog_ui_pages_show_local_previews_and_distinct_media_states(repo, tmp_path):
    from streamlit.testing.v1 import AppTest

    rows = [source(101 + i, name=f"Synthetic Row {i:03}", uuid=f"ui-{i:03}") for i in range(51)]
    images = [
        {
            **picture(uuid=f"ui-{i:03}", license=None if i == 3 else 1),
            "id": i + 1,
            "exercise": 101 + i,
        }
        for i in range(4)
    ]
    publish_snapshot(repo, snapshot(tmp_path, rows, images=images))
    fetch_media(
        repo,
        tmp_path / "blobs",
        downloader=lambda _: (png(), "image/png"),
        media_ids={"wger.image.1"},
    )
    repo.conn.execute(
        "UPDATE catalog_media SET fetch_status='failed' WHERE media_id='wger.image.3'"
    )
    repo.conn.commit()
    script = (
        "from healthzip.db.repository import Repository\n"
        "from healthzip.training.service import TrainingService\n"
        "from healthzip.ui.training_page import _selector\n"
        f"repo=Repository({str(repo.path)!r})\n"
        "_selector(TrainingService(repo),'catalog')\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    app.text_input(key="catalog_query").set_value("catalog.wger.ui-").run(timeout=30)
    assert not app.exception
    preview = app.dataframe(key="catalog_results").value
    assert len(preview) == 50
    assert any(str(x).startswith("data:image/jpeg;base64,") for x in preview["缩略图"])
    assert set(preview["器械"]) == {"哑铃"} and set(preview["部位"]) == {"背"}
    assert {"暂无动作示范", "尚未下载", "下载失败，暂不可用", "媒体许可不明，暂不可用"} <= set(
        preview["示范状态"]
    )
    selected_id = TrainingService(repo).search_exercises("catalog.wger.ui-")[3]["exercise_id"]
    app.session_state["catalog_results"] = {"selection": {"rows": [3], "columns": [], "cells": []}}
    app.run(timeout=30)
    assert app.selectbox(key="catalog_choice").value == selected_id and not app.exception
    app.number_input(key="catalog_page").set_value(2).run(timeout=30)
    assert not app.exception
    assert len(app.dataframe(key="catalog_results").value) == 1


def test_media_interruption_resumes_with_origin_validator(tmp_path):
    from email.message import Message

    from healthzip.training.catalog_media import resumable_download

    body, requests = png(), []

    class Response:
        def __init__(self, offset, fail=False):
            self.status = 206 if offset else 200
            self.headers = Message()
            self.headers["Content-Type"] = "image/png"
            self.headers["Content-Length"] = str(len(body) - offset)
            self.headers["ETag"] = '"synthetic-etag"'
            if offset:
                self.headers["Content-Range"] = f"bytes {offset}-{len(body) - 1}/{len(body)}"
            self.offset, self.fail, self.calls = offset, fail, 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, amount):
            self.calls += 1
            if self.fail:
                if self.calls == 1:
                    return body[:10]
                raise OSError("synthetic connection lost")
            if self.calls == 1:
                return body[self.offset :]
            return b""

    def opener(request, **kwargs):
        requests.append(dict(request.header_items()))
        return Response(10 if len(requests) > 1 else 0, fail=len(requests) == 1)

    with pytest.raises(OSError):
        resumable_download("https://wger.de/media/synthetic.png", tmp_path, opener=opener)
    raw, mime, _, _ = resumable_download(
        "https://wger.de/media/synthetic.png", tmp_path, opener=opener
    )
    assert raw == body and mime == "image/png"
    assert requests[1]["Range"] == "bytes=10-" and requests[1]["If-range"] == '"synthetic-etag"'


@pytest.mark.parametrize("changed", ["ETag", "Content-Range", "Content-Length"])
def test_resume_rejects_changed_origin_without_touching_partial(tmp_path, changed):
    import hashlib
    from email.message import Message

    from healthzip.training.catalog_media import resumable_download

    url = "https://wger.de/media/synthetic.png"
    body = png()
    folder = tmp_path / "partial"
    folder.mkdir()
    key = hashlib.sha256(url.encode()).hexdigest()
    part, info = folder / (key + ".partial"), folder / (key + ".json")
    part.write_bytes(body[:10])
    receipt = {"url": url, "validator": '"original"', "expected_total": len(body),
               "mime": "image/png"}
    info.write_text(json.dumps(receipt))

    class Response:
        status = 206
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, amount):
            pytest.fail("Invalid origin response must be rejected before reading bytes")

    response = Response()
    response.headers["ETag"] = '"original"'
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Length"] = str(len(body) - 10)
    response.headers["Content-Range"] = f"bytes 10-{len(body) - 1}/{len(body)}"
    response.headers.replace_header(changed, {
        "ETag": '"changed"',
        "Content-Range": f"bytes 10-{len(body)}/{len(body) + 1}",
        "Content-Length": str(len(body) - 9),
    }[changed])
    with pytest.raises(ValueError):
        resumable_download(url, tmp_path, opener=lambda *args, **kwargs: response)
    assert part.read_bytes() == body[:10]
    assert json.loads(info.read_text()) == receipt


def test_license_revoked_during_download_cannot_publish_blob(repo, tmp_path):
    import sqlite3

    publish_snapshot(repo, snapshot(tmp_path, images=[picture()]))

    def revoked(_):
        with sqlite3.connect(repo.path) as connection:
            connection.execute(
                "UPDATE catalog_media SET license_allowed=0,fetch_status='withdrawn'"
            )
        return png(), "image/png"

    result = fetch_media(repo, tmp_path / "blobs", downloader=revoked)
    assert not result["failed"]
    assert media_for(repo.conn, "catalog.wger.synthetic-row")[0]["local_path"] is None
    assert repo.conn.execute("SELECT fetch_status FROM catalog_media").fetchone()[0] == "withdrawn"


def test_offline_package_uses_installed_ids_and_local_media(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path, images=[picture()]))
    fetch_media(repo, tmp_path / "blobs", downloader=lambda _: (png(), "image/png"))
    svc = TrainingService(repo)
    svc.create_exercise("私人隐私测试", "repetitions", "other", "unknown")
    output = tmp_path / "catalog.zip"
    result = offline_package(repo, output)
    assert result["exercises"] == 47 and result["media_included"] == 1
    with ZipFile(output) as archive:
        html = archive.read("index.html").decode()
        assert "catalog.wger.synthetic-row" in html and "私人隐私测试" not in html
        assert "indexedDB.open" in html and "__CATALOG_SNAPSHOT_JSON__" not in html
        assert any(name.startswith("media/") for name in archive.namelist())
    assert "catalog.wger.synthetic-row" in recorder_html(repo).decode()
    assert browser_bootstrap(repo)["catalog_snapshot_id"]


def test_legacy_46_and_condition_keys_survive_publication(repo, tmp_path):
    svc = TrainingService(repo)
    before = svc.search_exercises()
    svc.add_alias("psa.ex.smith_incline_press", "私人史密斯")
    svc.favorite("psa.ex.smith_incline_press")
    session = svc.start_session("old")
    instance = svc.add_exercise(
        session["id"],
        "psa.ex.smith_incline_press",
        {"load_basis": "plates_per_side_kg", "load_basis_confirmed": True},
    )
    row = svc.add_set(
        instance["id"],
        {"completion_state": "completed", "load_value": "30", "load_unit": "kg", "reps": 10},
    )
    publish_snapshot(repo, snapshot(tmp_path))
    for old in before:
        assert svc.get_exercise(old["exercise_id"], 1)["definition_version"] == 1
    assert svc.get_set(row["set_uuid"])["condition_key"] == row["condition_key"]
    assert svc.get_set(row["set_uuid"])["load_value"] == "30"
    assert svc.search_exercises("私人史密斯")[0]["favorite"]


def test_no_source_muscle_tag_promotes_professional_relation(repo, tmp_path):
    publish_snapshot(repo, snapshot(tmp_path))
    item = TrainingService(repo).exercise_details("catalog.wger.synthetic-row")
    assert item["upstream_muscle_tags"]["use"] == "navigation"
    assert item["reviewed_anatomy"] is None and item["muscle_participation_proposals"] == []


def test_f05_real_ui_new_session_and_explicit_resume(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "ui.sqlite3"
    script = (
        "from healthzip.db.repository import Repository\nfrom healthzip.ui.training_page import render_training\n"
        f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()"
    )
    app = AppTest.from_string(script).run(timeout=30)
    app.text_input(key="start_name").set_value("第一场")
    app.button(key="training_start").click().run(timeout=30)
    first = app.selectbox(key="resume_training").value
    app.text_input(key="start_name").set_value("第二场")
    app.button(key="training_start").click().run(timeout=30)
    second = app.selectbox(key="resume_training").value
    assert first != second and not app.exception
    app.text_input(key="session_selector_query").set_value("杠铃平板卧推").run(timeout=30)
    app.selectbox(key="session_condition_basis").set_value("unknown")
    next(b for b in app.button if b.label == "添加到本次训练").click().run(timeout=30)
    repo = Repository(path)
    svc = TrainingService(repo)
    assert not svc.get_session(first)["exercises"]
    assert svc.get_session(second)["exercises"][0]["catalog_id"] == "psa.ex.barbell_bench_press"
    second_instance = svc.get_session(second)["exercises"][0]["id"]
    repo.close()
    app.button(key="add_set_" + second_instance).click().run(timeout=30)
    repo = Repository(path)
    second_set = TrainingService(repo).get_session(second)["sets"][0]["set_uuid"]
    repo.close()
    app.text_input(key="set_" + second_set + "_reps").set_value("8")
    app.button(key="set_" + second_set + "_completed").click().run(timeout=30)
    app.selectbox(key="resume_training").set_value(first).run(timeout=30)
    app.text_input(key="session_selector_query").set_value("平板支撑").run(timeout=30)
    app.selectbox(key="session_selector_choice").set_value("psa.ex.plank")
    app.selectbox(key="session_condition_basis").set_value("unknown")
    next(b for b in app.button if b.label == "添加到本次训练").click().run(timeout=30)
    assert not app.exception
    repo = Repository(path)
    assert TrainingService(repo).get_session(first)["exercises"][0]["catalog_id"] == "psa.ex.plank"
    assert len(TrainingService(repo).get_session(second)["exercises"]) == 1
    assert TrainingService(repo).get_session(second)["sets"][0]["reps"] == 8
    assert not TrainingService(repo).get_session(first)["sets"]
    repo.close()


def test_template_and_exchange_preserve_original_display_and_semantics(repo, tmp_path):
    from healthzip.training.exchange import export_training, import_training

    svc = TrainingService(repo)
    custom = svc.create_exercise("历史名称", "duration", "bodyweight", "unknown")
    session = svc.start_session("old")
    instance = svc.add_exercise(
        session["id"], custom["exercise_id"], {}, {"sets": [{"duration_s": 30}]}
    )
    row = instance["sets"][0]
    svc.edit_set(
        row["set_uuid"],
        {"completion_state": "completed", "duration_s": 30},
        base_revision=row["revision"],
    )
    renamed = svc.update_exercise(custom["exercise_id"], {"name_zh": "新名字"}, base_revision=1)
    template = svc.save_session_as_template(session["id"], "历史模板")
    restarted = svc.start_session("copy", template_id=template["id"])
    assert restarted["exercises"][0]["exercise"]["name"] == "历史名称"
    assert browser_bootstrap(repo)["catalog_definitions"][0]["name"] == "历史名称"
    svc.update_exercise(
        custom["exercise_id"], {"recording_mode": "distance"}, base_revision=renamed["revision"]
    )
    output = export_training(repo, tmp_path / "history.json")
    target = Repository(tmp_path / "restored.sqlite3")
    import_training(target, output)
    imported = TrainingService(target).get_session(session["session_uuid"])
    assert imported["exercises"][0]["definition_version"] == 1
    assert imported["exercises"][0]["exercise"]["name"] == "历史名称"
    assert imported["sets"][0]["duration_s"] == 30
    target.close()


@pytest.mark.parametrize(
    "change",
    ["translation_name", "media", "timestamp", "equipment", "description", "identity_name"],
)
def test_legacy_mapping_survives_only_presentation_changes(repo, tmp_path, monkeypatch, change):
    """A reviewed identity survives label/media refresh, not changed identity evidence."""
    from copy import deepcopy

    original = source()
    original["translations"].append(
        {
            "id": 301,
            "language": 3,
            "name": "原始中文译名",
            "description": "非身份核对原文语言的译文",
            "aliases": [],
        }
    )
    languages = [{"id": 2, "short_name": "en"}, {"id": 3, "short_name": "zh-cn"}]
    legacy_id = "psa.ex.barbell_bench_press"
    mapping = {
        "source_uuid": original["uuid"],
        "local_exercise_id": legacy_id,
        "relation": "exact_identity",
        "status": "confirmed",
        "source_name": original["translations"][0]["name"],
        "evidence": {
            "source_record_sha256": digest(original),
            "locator": "exerciseinfo/101/translations/language=2",
        },
        "reviewer_kind": "synthetic_identity_mapping_fixture",
    }
    read_text = Path.read_text

    def read_mapping(path, *args, **kwargs):
        if path.name == "catalog_legacy_mapping.json":
            return encoded({"mappings": [mapping]})
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_mapping)
    publish_snapshot(repo, snapshot(tmp_path, [original], images=[picture()], languages=languages))
    fetch_media(repo, tmp_path / "blobs", downloader=lambda _: (png(), "image/png"))
    svc = TrainingService(repo)
    session = svc.start_session("synthetic mapped history")
    instance = svc.add_exercise(session["id"], legacy_id, {})
    svc.favorite(legacy_id)
    svc.add_alias(legacy_id, "本地私人名称")
    changed = deepcopy(original)
    if change == "translation_name":
        changed["translations"][1]["name"] = "新版中文译名"
        changed["translations"][0]["aliases"].append({"alias": "新版显示别名"})
    elif change == "media":
        changed["images"] = [{"id": 9001, "image": "https://wger.de/media/new.png"}]
    elif change == "timestamp":
        changed["last_update_global"] = "2026-11-12T01:00:00Z"
    elif change == "equipment":
        changed["equipment"] = [{"id": 2, "name": "Kettlebell"}]
    elif change == "identity_name":
        changed["translations"][0]["name"] = "Different Incline Variant"
    else:
        changed["translations"][0]["description"] = "A different physical task"
    publish_snapshot(
        repo,
        snapshot(tmp_path, [changed], images=[picture()], languages=languages, suffix="updated"),
    )
    actual = repo.conn.execute(
        "SELECT status FROM catalog_source_mapping WHERE source_uuid=? AND local_exercise_id=?",
        (original["uuid"], legacy_id),
    ).fetchone()[0]
    if change in {"equipment", "description", "identity_name"}:
        assert actual == "needs_identity_review"
        assert svc.search_exercises("catalog.wger.synthetic-row")
    else:
        assert actual == "confirmed"
        assert not svc.search_exercises("catalog.wger.synthetic-row")
        assert svc.search_exercises("本地私人名称")[0]["favorite"]
        assert svc.get_exercise(legacy_id)["definition_version"] == 1
        assert media_for(repo.conn, legacy_id)[0]["fetch_status"] == "ready"
        # Repeated display refresh still binds to the original reviewed bytes.
        changed["last_update_global"] = "2026-11-12T02:00:00Z"
        publish_snapshot(
            repo,
            snapshot(tmp_path, [changed], images=[picture()], languages=languages, suffix="again"),
        )
        saved = repo.conn.execute(
            "SELECT evidence_json FROM catalog_source_mapping WHERE source_uuid=? "
            "AND local_exercise_id=?",
            (original["uuid"], legacy_id),
        ).fetchone()[0]
        assert json.loads(saved)["current_evidence_check"][
            "reviewed_source_record_sha256"
        ] == digest(original)
        assert not svc.search_exercises("catalog.wger.synthetic-row")
    assert svc.get_session_exercise(instance["id"])["condition_key"] == instance["condition_key"]
    assert svc.get_session_exercise(instance["id"])["exercise"] == instance["exercise"]
