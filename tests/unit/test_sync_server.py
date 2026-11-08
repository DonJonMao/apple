import http.client
import json
import threading

from healthzip.db.repository import Repository
from healthzip.sync_server import HealthZipHTTPServer


def _payload():
    return {
        "data": {
            "metrics": [
                {
                    "name": "resting_heart_rate",
                    "units": "count/min",
                    "data": [
                        {
                            "id": "server-rhr-1",
                            "qty": 58,
                            "date": "2026-11-08T08:00:00+08:00",
                            "source": "Test Watch",
                        }
                    ],
                }
            ]
        }
    }


def _request(port, path, body=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-HealthZip-Token"] = token
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    conn.request("GET" if body is None else "POST", path, body=encoded, headers=headers)
    response = conn.getresponse()
    result = json.loads(response.read().decode("utf-8"))
    conn.close()
    return response.status, result


def test_local_receiver_requires_token_and_is_idempotent(tmp_path):
    db_path = tmp_path / "health.sqlite3"
    server = HealthZipHTTPServer(("127.0.0.1", 0), db_path, "secret-token", 1024 * 1024)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, health = _request(port, "/health")
        assert status == 200
        assert health["status"] == "ok"
        status, _ = _request(port, "/v1/ingest/health", _payload())
        assert status == 401
        status, first = _request(port, "/v1/ingest/health", _payload(), "secret-token")
        assert status == 200
        assert first["new"] == 1
        status, repeated = _request(port, "/v1/ingest/health", _payload(), "secret-token")
        assert status == 200
        assert repeated["duplicate"] == 1
        repo = Repository(db_path)
        assert repo.count("health_sample") == 1
        repo.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
