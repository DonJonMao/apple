"""AppTest transport for the real workbench; browser tests cover its DOM.

Only Streamlit's component message channel is replaced. The app router,
command validation, TrainingService, SQLite events and scientific rules remain
real. Tests must never use this harness as evidence for browser interactions.
"""
from uuid import uuid4


def install(monkeypatch):
    import streamlit as st

    from healthzip.ui import training_workbench

    def transport(*, snapshot, receipt, **kwargs):
        st.session_state["strength_test_snapshot"] = snapshot
        st.session_state["strength_test_receipt"] = receipt
        return st.session_state.pop("strength_test_command", None)

    monkeypatch.setattr(training_workbench, "_component", transport)


def send(app, action, payload=None, *, command_id=None):
    if any(button.key == "strength_secondary_back" for button in app.button):
        app.button(key="strength_secondary_back").click().run(timeout=30)
    app.session_state["strength_test_command"] = {
        "id": command_id or str(uuid4()), "action": action, "payload": payload or {},
    }
    app.run(timeout=30)
    assert not app.exception, [item.value for item in app.exception]
    return app.session_state["strength_test_receipt"]


def snapshot(app):
    return app.session_state["strength_test_snapshot"]


def legacy(app, view, **payload):
    send(app, "legacy", {"view": view, **payload})
    return app


def back(app):
    app.button(key="strength_secondary_back").click().run(timeout=30)
    assert not app.exception
    return app


def management(app, view):
    legacy(app, "management")
    app.selectbox(key="strength_management_view").set_value(view).run(timeout=30)
    assert not app.exception
    return app
