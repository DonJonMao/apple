"""Revocation affects queued work and the actual optional-model send boundary."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from healthzip.ai import client
from healthzip.ai.consent import NetworkConsent, network_allowed


def analysis():
    return {"cards": [{"id": "synthetic", "title": "Synthetic", "status": "usable",
        "summary": "Synthetic observation.", "facts": [], "limitations": [],
        "allowed_actions": ["continue_observation"]}]}


def test_withdrawn_grant_never_revives_after_new_authorization():
    consent = NetworkConsent(True)
    old = consent.grant()
    assert old()
    consent.set_allowed(False)
    assert not old()
    consent.set_allowed(True)
    fresh = consent.grant()
    assert fresh() and not old()
    assert old.identity != fresh.identity
    assert fresh.identity != NetworkConsent(True).grant().identity


def test_revocation_during_payload_preparation_is_checked_at_transport(monkeypatch):
    consent = NetworkConsent(True)
    grant = consent.grant()
    original = client.Request

    def revoke_after_build(*args, **kwargs):
        request = original(*args, **kwargs)
        consent.set_allowed(False)
        return request

    monkeypatch.setattr(client, "Request", revoke_after_build)
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("withdrawn grant reached transport")))
    result = client.explain_analysis(analysis(), allow_network=grant,
        config=client.AIConfig("http://example.invalid", "synthetic", "synthetic"))
    assert result["source"] == "local_fallback"


def test_queued_job_uses_current_grant_when_it_starts(monkeypatch):
    consent = NetworkConsent(True)
    grant = consent.grant()
    entered, release = Event(), Event()
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("withdrawn queued job reached transport")))

    def occupy_worker():
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(occupy_worker)
        try:
            assert entered.wait(2)
            future = executor.submit(client.explain_analysis, analysis(), allow_network=grant,
                config=client.AIConfig("http://example.invalid", "synthetic", "synthetic"))
            assert not future.running()
            consent.set_allowed(False)
            consent.set_allowed(True)
        finally:
            release.set()
        blocker.result(timeout=2)
        assert future.result(timeout=2)["source"] == "local_fallback"


def test_broken_dynamic_consent_check_fails_closed():
    def failed_check():
        raise RuntimeError("unavailable grant")

    assert not network_allowed(failed_check)
