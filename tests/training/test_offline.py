import http.client
import json
import threading

import pytest

from healthzip.db.repository import Repository
from healthzip.sync_server import HealthZipHTTPServer
from healthzip.training import TrainingService
from healthzip.training.offline import apply_event_batch, browser_bootstrap, recorder_html


def events():
    return [
        {
            "event_id": "offline-session",
            "operation": "start_session",
            "arguments": {
                "name": "离线合成训练",
                "session_id": "client-session",
                "started_at": "2026-11-11T10:00:00+08:00",
            },
        },
        {
            "event_id": "offline-exercise",
            "operation": "add_exercise",
            "arguments": {
                "session_id": "client-session",
                "exercise_id": "psa.ex.smith_incline_press",
                "session_exercise_id": "client-exercise",
                "condition": {},
                "populate_sets": False,
            },
        },
        {
            "event_id": "offline-set-a",
            "operation": "add_set",
            "arguments": {
                "session_exercise_id": "client-exercise",
                "set_id": "client-set-a",
                "actual": {
                    "completion_state": "completed",
                    "load_value": 30,
                    "load_unit": "kg",
                    "reps": 10,
                },
            },
        },
        {
            "event_id": "offline-set-b",
            "operation": "add_set",
            "arguments": {
                "session_exercise_id": "client-exercise",
                "set_id": "client-set-b",
                "actual": {
                    "completion_state": "completed",
                    "load_value": 30,
                    "load_unit": "kg",
                    "reps": 10,
                },
            },
        },
    ]


def test_offline_batch_replay_after_lost_response_no_duplicate_real_sets(tmp_path):
    repo = Repository(tmp_path / "offline.sqlite3")
    first = apply_event_batch(repo, events(), device_id="offline-browser")
    assert all(x["status"] == "applied" for x in first["results"])
    repo.close()
    repo = Repository(tmp_path / "offline.sqlite3")
    second = apply_event_batch(repo, events(), device_id="offline-browser")
    assert all(x["result"]["replayed"] for x in second["results"])
    assert repo.count("strength_set") == 2
    assert TrainingService(repo).get_session("client-session")["completed_sets"] == 2
    bootstrap = browser_bootstrap(repo)
    assert len(bootstrap["catalog"]) == 46
    assert bootstrap["sessions"][0]["session_uuid"] == "client-session"
    repo.close()


def test_offline_conflict_retains_server_fact_and_blocks_dependent_events(tmp_path):
    repo = Repository(tmp_path / "offline.sqlite3")
    apply_event_batch(repo, events())
    svc = TrainingService(repo)
    svc.edit_set("client-set-a", {"reps": 9}, base_revision=1)
    result = apply_event_batch(
        repo,
        [
            {
                "event_id": "other-device",
                "operation": "edit_set",
                "arguments": {"set_id": "client-set-a", "changes": {"reps": 8}, "base_revision": 1},
            },
            {
                "event_id": "dependent",
                "operation": "edit_set",
                "arguments": {"set_id": "client-set-a", "changes": {"reps": 7}, "base_revision": 2},
            },
        ],
    )
    assert result["processed"] == 1 and result["results"][0]["status"] == "conflicted"
    assert svc.get_set("client-set-a")["reps"] == 9
    conflict = result["results"][0]["result"]["conflict_id"]
    resolved = apply_event_batch(
        repo,
        [
            {
                "event_id": "user-resolution",
                "operation": "resolve_conflict",
                "arguments": {"conflict_id": conflict, "choice": "apply_proposed"},
            }
        ],
    )
    assert resolved["results"][0]["result"]["reps"] == 8
    repo.close()


def test_offline_api_operation_allowlist_and_scope(tmp_path):
    repo = Repository(tmp_path / "offline.sqlite3")
    for event in [
        {"event_id": "evil", "operation": "__getattribute__", "arguments": {"name": "conn"}},
        {"event_id": "evil", "operation": "start_session", "arguments": {"user_id": "other"}},
        {"operation": "start_session", "arguments": {}},
    ]:
        with pytest.raises(ValueError):
            apply_event_batch(repo, [event])
    assert repo.count("strength_session") == 0
    repo.close()


def request(server, method, path, body=None, token=None, origin=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-HealthZip-Token"] = token
    if origin:
        headers["Origin"] = origin
    encoded = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, encoded, headers)
    response = connection.getresponse()
    result = (response.status, dict(response.getheaders()), response.read())
    connection.close()
    return result


def test_local_training_http_token_cors_and_download(tmp_path):
    server = HealthZipHTTPServer(
        ("127.0.0.1", 0), tmp_path / "server.sqlite3", "synthetic-token", 1024 * 1024
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert request(server, "GET", "/v1/training/bootstrap")[0] == 401
        status, headers, body = request(server, "GET", "/training/offline?download=1")
        assert status == 200 and "attachment" in headers["Content-Disposition"]
        assert b"__PUBLIC_CATALOG_JSON__" not in body
        assert b"synthetic-token" not in body
        status, headers, _ = request(server, "OPTIONS", "/v1/training/events", origin="null")
        assert status == 204 and headers["Access-Control-Allow-Origin"] == "null"
        assert (
            request(server, "OPTIONS", "/v1/training/events", origin="https://unrelated.example")[0]
            == 403
        )
        status, headers, body = request(
            server, "POST", "/v1/training/events", {"events": events()}, "synthetic-token", "null"
        )
        assert status == 200 and headers["Access-Control-Allow-Origin"] == "null"
        assert all(r["status"] == "applied" for r in json.loads(body)["results"])
        assert (
            request(
                server,
                "POST",
                "/v1/training/events",
                {"events": []},
                "synthetic-token",
                "https://unrelated.example",
            )[0]
            == 403
        )
        status, _, body = request(server, "GET", "/v1/training/catalog", token="synthetic-token")
        assert status == 200 and len(json.loads(body)["catalog"]) == 46
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_recorder_is_self_contained_and_no_credential_embedded():
    text = recorder_html().decode()
    assert "<script src=" not in text and "<link " not in text
    assert "localStorage.setItem" in text
    assert "client_event_id" not in text  # domain transport uses event_id consistently
    assert "event_id:uuid()" in text
    assert "crypto.getRandomValues" in text
