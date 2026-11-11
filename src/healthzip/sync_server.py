"""Small local HTTP receiver for phone-side incremental exporters."""

from __future__ import annotations

import hmac
import json
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import urlparse

from healthzip.db.repository import Repository
from healthzip.importers.incremental import import_json_payload
from healthzip.strength_log import save_strength_log
from healthzip.training.offline import apply_event_batch, browser_bootstrap, recorder_html


def _token(headers: Any) -> str:
    value = headers.get("X-HealthZip-Token", "")
    if value:
        return str(value).strip()
    authorization = headers.get("Authorization", "")
    if str(authorization).lower().startswith("bearer "):
        return str(authorization)[7:].strip()
    return ""


def _inbox_path(db_path: Path, raw: bytes, source: str) -> Path:
    inbox = db_path.parent / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    digest = __import__("hashlib").sha256(raw).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in source)[:40]
    path = inbox / f"{stamp}_{safe}_{digest}.json"
    path.write_bytes(raw)
    return path


class _HealthZipHandler(BaseHTTPRequestHandler):
    server: "HealthZipHTTPServer"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Health payloads are sensitive; log only method/path/status, never body.
        print(f"healthzip-sync {self.command} {self.path} " + format % args)

    def _respond(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return bool(self.server.token) and hmac.compare_digest(
            _token(self.headers), self.server.token
        )

    def _cors_headers(self) -> None:
        # A downloaded standalone recorder has Origin:null. It still must send
        # the secret token; arbitrary website origins receive no CORS permission.
        origin = self.headers.get("Origin")
        if origin == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Vary", "Origin")

    def _training_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or origin == "null":
            return True
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == self.headers.get("Host")

    def do_OPTIONS(self) -> None:  # noqa: N802
        if (
            not urlparse(self.path).path.startswith("/v1/training/")
            or not self._training_origin_allowed()
        ):
            self._respond(403, {"error": "origin_not_allowed"})
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-HealthZip-Token")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/training/offline":
            repo = Repository(self.server.db_path)
            try:
                body = recorder_html(repo)
            finally:
                repo.close()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src http: https:; img-src 'self' blob: data:; media-src 'self' blob:; base-uri 'none'; form-action 'none'",
            )
            if "download=1" in self.path:
                self.send_header(
                    "Content-Disposition", 'attachment; filename="HealthZIP-offline.html"'
                )
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/v1/training/media/"):
            if not self._authorized() or not self._training_origin_allowed():
                self._respond(401, {"error": "unauthorized"})
                return
            from healthzip.training.catalog_media import local_media

            repo = Repository(self.server.db_path)
            try:
                location, mime = local_media(repo.conn, path.rsplit("/", 1)[-1])
                body = location.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except ValueError:
                self._respond(404, {"error": "media_unavailable"})
            finally:
                repo.close()
            return
        if path in {"/v1/training/bootstrap", "/v1/training/catalog", "/v1/training/sessions"}:
            if not self._authorized() or not self._training_origin_allowed():
                self._respond(401, {"error": "unauthorized"})
                return
            repo = Repository(self.server.db_path)
            try:
                result = browser_bootstrap(repo)
                if path.endswith("/catalog"):
                    from urllib.parse import parse_qs

                    from healthzip.training.service import TrainingService

                    query = parse_qs(urlparse(self.path).query)
                    try:
                        result = TrainingService(repo).search_catalog(
                            query.get("q", [""])[0],
                            offset=int(query.get("offset", [0])[0]),
                            limit=int(query.get("limit", [50])[0]),
                        )
                        result["catalog"] = result["items"]  # v1.3 clients keep their field name.
                        result["schema_version"] = "1.4.0"
                    except ValueError as exc:
                        self._respond(400, {"error": str(exc)})
                        return
                elif path.endswith("/sessions"):
                    result = {"sessions": result["sessions"], "conflicts": result["conflicts"]}
                self._respond(200, result)
            finally:
                repo.close()
            return
        if path == "/health":
            self._respond(200, {"status": "ok", "service": "healthzip-sync"})
            return
        self._respond(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._respond(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path not in {
            "/v1/ingest/health",
            "/v1/ingest/health-auto-export",
            "/v1/ingest/strength",
            "/v1/training/events",
        }:
            self._respond(404, {"error": "not_found"})
            return
        if path == "/v1/training/events" and not self._training_origin_allowed():
            self._respond(403, {"error": "origin_not_allowed"})
            return
        length_text = self.headers.get("Content-Length", "")
        try:
            length = int(length_text)
        except ValueError:
            self._respond(411, {"error": "content_length_required"})
            return
        if length < 0 or length > self.server.max_body_bytes:
            self._respond(413, {"error": "payload_too_large"})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._respond(400, {"error": "invalid_json", "message": str(exc)[:300]})
            return

        source_name = (
            self.headers.get("X-HealthZip-Source", "phone_export").strip() or "phone_export"
        )
        repo = Repository(self.server.db_path)
        try:
            if path == "/v1/training/events":
                result = apply_event_batch(
                    repo, payload.get("events"), device_id=payload.get("device_id", "browser-local")
                )
                self._respond(200, result)
                return
            inbox = _inbox_path(self.server.db_path, raw, source_name)
            if path == "/v1/ingest/strength":
                session = payload.get("session") or {}
                sets = payload.get("sets") or []
                result = save_strength_log(
                    repo,
                    session_date=str(session.get("session_date") or ""),
                    started_at=str(session.get("started_at") or ""),
                    name=str(session.get("name") or ""),
                    notes=str(session.get("notes") or ""),
                    sets=sets,
                )
                self._respond(200, {"status": "completed", "inbox": str(inbox), **result})
                return
            result = import_json_payload(
                payload,
                repo,
                source_name=source_name,
                source_kind="health_auto_export",
                source_ref=str(inbox),
                raw_bytes=raw,
            )
            self._respond(200, {"inbox": str(inbox), **result.as_dict()})
        except (ValueError, KeyError) as exc:
            self._respond(400, {"error": "invalid_payload", "message": str(exc)[:300]})
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self._respond(500, {"error": "ingest_failed", "message": str(exc)[:300]})
        finally:
            repo.close()


class HealthZipHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        db_path: Path,
        token: str,
        max_body_bytes: int,
    ) -> None:
        super().__init__(server_address, _HealthZipHandler)
        self.db_path = db_path
        self.token = token
        self.max_body_bytes = max_body_bytes


def serve(
    db_path: Union[str, Path],
    *,
    bind: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    max_body_bytes: int = 20 * 1024 * 1024,
) -> None:
    """Run a token-protected local receiver until interrupted."""
    if not token:
        token = secrets.token_urlsafe(24)
    if max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be positive")
    server = HealthZipHTTPServer(
        (bind, int(port)), Path(db_path).expanduser().resolve(), token, max_body_bytes
    )
    print(f"Health ZIP sync server listening on http://{bind}:{port}")
    print(f"Health ZIP sync token: {token}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["HealthZipHTTPServer", "serve"]
