"""Basic measurements keep their actual date and use the canonical repository."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.db.temporal_schema import samples_as_of
from healthzip.normalize import quantity_value
from healthzip.science.contracts import instant

GOALS = {None: "尚未选择", "strength": "力量表现", "hypertrophy": "肌肉增长", "general_fitness": "一般体能"}


def latest_measurements(repo):
    cutoff = datetime.now(timezone.utc).isoformat()
    found = {}
    for table in ("health_sample", "body_measurement"):
        for row in samples_as_of(repo, cutoff, table, canonical_types=["height_cm", "body_mass_kg"]):
            numeric = quantity_value(row)
            when = row.get("end_utc") or row.get("measured_at")
            kind = row["canonical_type"]
            if when and numeric["value"] is not None and numeric["value"] > 0:
                if kind not in found or instant(when) > instant(found[kind]["measured_at"]):
                    found[kind] = {"value": numeric["value"], "unit": numeric["unit"], "measured_at": when,
                                   "source": row.get("source_name") or row.get("source") or "来源未注明"}
    return found


def render_basic_profile(repo, timezone_name):
    from healthzip.advice import profile, save_profile
    from healthzip.training.service import TrainingService
    st.write("基础资料")
    found = latest_measurements(repo)
    columns = st.columns(2)
    for column, kind, label in zip(columns, ("height_cm", "body_mass_kg"), ("身高", "体重")):
        with column:
            value = found.get(kind)
            if value:
                st.metric(label, f"{value['value']:g} {value['unit']}")
                st.caption(f"测量于 {value['measured_at']} · {value['source']}")
            else:
                st.write(label + "尚未记录")
    st.caption("缺少某项只影响依赖它的计算，仍可查看健康记录和记录训练。")
    with st.expander("补充实际测量"):
        with st.form("basic_measurement"):
            kind = st.selectbox("测量项目", ["height_cm", "body_mass_kg"], format_func=lambda key: "身高（cm）" if key == "height_cm" else "体重（kg）")
            value = st.number_input("实际测量值", min_value=0.0, value=None, step=0.1)
            now = datetime.now(ZoneInfo(timezone_name))
            day = st.date_input("测量日期", value=now.date(), max_value=now.date())
            observed_time = st.time_input("测量时间", value=now.time().replace(second=0, microsecond=0))
            if st.form_submit_button("保存这次测量"):
                observed = datetime.combine(day, observed_time, ZoneInfo(timezone_name))
                if value is None or value <= 0:
                    st.error("请填写实际测量的正数。")
                elif observed > now:
                    st.error("测量时间须在当前时刻之前。")
                else:
                    with repo.transaction():
                        repo.conn.execute("INSERT INTO body_measurement(fingerprint,measured_at,local_date,body_part,value,unit,canonical_type,source) VALUES(?,?,?,?,?,?,?,?)",
                            (uuid4().hex, observed.isoformat(), day.isoformat(), "height" if kind == "height_cm" else "body_mass", value,
                             "cm" if kind == "height_cm" else "kg", kind, "用户手动测量"))
                    st.success("这次测量已保存，可以在身体详情中查看。")
    exists = repo.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='advice_profile_revision'")
    current = profile(repo)["fields"] if exists else {}
    with st.form("basic_profile"):
        age = st.number_input("年龄（可留空）", min_value=0.0, value=float(current["age"]) if current.get("age") is not None else None, step=1.0)
        goal = st.selectbox("当前目标", list(GOALS), index=list(GOALS).index(current.get("training_goal")) if current.get("training_goal") in GOALS else 0, format_func=GOALS.get)
        if st.form_submit_button("保存基础资料与目标"):
            TrainingService(repo)
            save_profile(repo, {**current, "age": age, "training_goal": goal})
            st.success("基础资料与目标已保存，未填写的年龄保持未知。")
