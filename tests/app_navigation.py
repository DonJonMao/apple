"""Use the current five-entry app navigation in integration regressions."""

BODY = {"心率", "睡眠", "体重", "有氧", "夜间生理", "活动与行动能力", "环境", "健康与安全事件"}


def go(app, destination, *, timeout=None):
    arguments = {"timeout": timeout} if timeout is not None else {}
    main = "身体" if destination in BODY else "训练" if destination in {"力量", "运动"} else destination
    if destination == "运动":
        # This regression opens the retained workout route without entering the recorder.
        app.session_state["training_section"] = "运动记录"
    app.radio(key="main_workspace").set_value(main).run(**arguments)
    if destination in BODY:
        app.selectbox(key="body_section").set_value(destination).run(**arguments)
    elif destination == "运动":
        app.radio(key="training_section").set_value("运动记录").run(**arguments)
    return app


def legacy_analysis(app, section="问题分析"):
    app.radio(key="review_section").set_value(section).run()
    key = "review_custom_export" if section == "报告" else "review_advanced"
    app.toggle(key=key).set_value(True).run()
    return app
