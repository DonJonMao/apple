"""Narrow-screen training workflow backed by the private Repository."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import streamlit as st

from healthzip.db.repository import Repository
from healthzip.training.offline import recorder_html
from healthzip.training.semantics import LOAD_BASES, load_change, numeric
from healthzip.training.service import TrainingService

LOAD_LABELS = {
    "unknown": "尚不明确",
    "external_total_kg": "含杆/器械的外部总重",
    "plates_per_side_kg": "单边配重片",
    "per_dumbbell_kg": "每只哑铃",
    "dumbbells_total_kg": "哑铃合计",
    "single_implement_kg": "单件器械重量",
    "machine_setting": "本台器械刻度",
    "bodyweight_no_external": "自重（无额外负重）",
    "added_load_kg": "额外负重",
    "assistance_setting": "助力大小",
    "band_configuration": "弹力带设置",
}
STOP_LABELS = {
    "unknown": "未记录",
    "plan_target": "完成计划",
    "target_rir": "达到目标余力",
    "volitional_failure": "无法继续完成",
    "technical_limit": "动作技术限制",
    "pain": "疼痛/不适",
    "other": "其他",
}
REGIONS = {
    "chest": "胸",
    "back": "背",
    "shoulders": "肩",
    "arms": "上臂/前臂",
    "glutes": "臀",
    "legs": "腿",
    "calves": "小腿",
    "core": "躯干/核心",
    "whole_body": "全身/搬运",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _act(function, *args, **kwargs):
    try:
        result = function(*args, **kwargs)
        if isinstance(result, dict) and result.get("status") == "conflicted":
            st.error("记录已被另一处修改；请在冲突处理中选择保留的版本。")
            return None
        return result
    except (ValueError, KeyError, OSError) as exc:
        st.error(str(exc))
        return None


def _set_form_fields(row, mode):
    measured = {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}[mode]
    suffixes = {
        "load_value": "load_value",
        measured: measured,
        "rir": "rir",
        "load_unit": "unit",
        "stop_reason": "stop",
        "set_type": "type",
        "quality_status": "quality",
        "rir_qualifier": "rir_qualifier",
        "rpe": "rpe",
        "rpe_scale": "rpe_scale",
        "pain_flag": "pain",
        "started_at": "start",
        "ended_at": "end",
        "relation_kind": "relation",
        "parent_set_uuid": "parent_set",
        "relation_group_id": "relation_id",
        "quality_note": "note",
    }
    suffixes.update(
        {
            field: "extra_" + field
            for field in (
                "body_mass_kg",
                "added_load_kg",
                "assistance_value",
                "duration_s",
                "distance_m",
                "rest_recorded_s",
                "rest_recorded_method",
            )
            if field != measured
        }
    )
    select_fields = {
        "load_unit",
        "stop_reason",
        "set_type",
        "quality_status",
        "rir_qualifier",
        "rpe_scale",
        "pain_flag",
        "relation_kind",
    }
    defaults = {"load_unit": "kg", "stop_reason": "unknown", "set_type": "work"}
    values = {}
    for field in suffixes:
        value = row.get(field)
        if field in defaults:
            value = value or defaults[field]
        if field == "pain_flag" and value is not None:
            value = bool(value)
        values[field] = value if field in select_fields else ("" if value is None else str(value))
    for field, suffix in (
        ("reps_min", "target_low"),
        ("reps_max", "target_high"),
        ("rir", "target_rir"),
    ):
        key = "planned." + field
        suffixes[key] = suffix
        value = (row.get("planned") or {}).get(field)
        values[key] = "" if value is None else str(value)
    return suffixes, values


def _form_dirty(prefix, baseline):
    dirty = set()
    numeric_fields = {
        "load_value",
        "reps",
        "rir",
        "rpe",
        "body_mass_kg",
        "added_load_kg",
        "assistance_value",
        "duration_s",
        "distance_m",
        "rest_recorded_s",
        "planned.reps_min",
        "planned.reps_max",
        "planned.rir",
    }
    for field, suffix in baseline["suffixes"].items():
        before = baseline["values"][field]
        current = st.session_state.get(prefix + "_" + suffix, before)
        if current == before:
            continue
        if field in numeric_fields:
            try:
                if numeric(current, field) == numeric(before, field):
                    continue
            except ValueError:
                pass
        dirty.add(field)
    return dirty


def _bind_set_form(row, mode, prefix):
    key = "training_form:" + prefix
    baseline = st.session_state.get(key)
    if baseline and baseline.get("sync"):
        for field, value in baseline.pop("sync").items():
            st.session_state[prefix + "_" + baseline["suffixes"][field]] = value
    if baseline is None or (
        baseline["revision"] != row["revision"] and not _form_dirty(prefix, baseline)
    ):
        suffixes, values = _set_form_fields(row, mode)
        baseline = {
            "revision": row["revision"],
            "suffixes": suffixes,
            "values": values,
            "mode": mode,
        }
        st.session_state[key] = baseline
        for field, suffix in suffixes.items():
            st.session_state[prefix + "_" + suffix] = values[field]
    return baseline


def _accept_set_form(row, prefix, mode, submitted):
    old = st.session_state.get("training_form:" + prefix)
    keep = (_form_dirty(prefix, old) if old else set()) - set(submitted)
    suffixes, values = _set_form_fields(row, mode)
    st.session_state["training_form:" + prefix] = {
        "revision": row["revision"],
        "suffixes": suffixes,
        "values": values,
        "mode": mode,
        "sync": {key: value for key, value in values.items() if key not in keep},
    }


def _draft_change(db_path, set_id, revision, widget_key, field, prefix, mode):
    repo = Repository(db_path)
    try:
        # Other callbacks from this same submission may already have committed
        # one field. Advance only to this form's acknowledged revision.
        revision = st.session_state.get("training_form:" + prefix, {}).get("revision", revision)
        value = st.session_state[widget_key]
        changes = {field: None if value == "" else value}
        if field == "load_value":
            changes["load_unit"] = st.session_state.get(
                widget_key.removesuffix("load_value") + "unit", "kg"
            )
        result = TrainingService(repo).edit_set(
            set_id, changes, base_revision=revision, event_id=str(uuid4())
        )
        if result.get("status") == "conflicted":
            st.session_state["training_notice"] = "草稿有版本冲突，请复核。"
        else:
            _accept_set_form(result, prefix, mode, changes)
    except ValueError as exc:
        st.session_state["training_notice"] = str(exc)
    finally:
        repo.close()


def _selector(svc, key):
    query = st.text_input("搜索动作或别名", key=key + "_query")
    view = st.selectbox(
        "动作列表",
        ["all", "recent", "favorites", "custom"],
        format_func=lambda x: {
            "all": "全部",
            "recent": "最近",
            "favorites": "收藏",
            "custom": "自定义",
        }[x],
        key=key + "_view",
    )
    regions = st.multiselect("部位", list(REGIONS), format_func=REGIONS.get, key=key + "_regions")
    catalog = svc.search_exercises()
    equipment = st.multiselect(
        "器械筛选", sorted({x["equipment_type"] for x in catalog}), key=key + "_equipment"
    )
    patterns = st.multiselect(
        "动作模式",
        sorted({p for x in catalog for p in x.get("movement_patterns", [])}),
        key=key + "_patterns",
    )
    matches = svc.search_exercises(
        query, regions=regions, equipment=equipment, patterns=patterns, view=view
    )
    st.caption(f"找到 {len(matches)} 个动作。分类用于查找；肌群映射未经审核不用于定量剂量。")
    if not matches:
        st.info("可清除筛选或在“动作维护”中新建动作。")
        return None
    ids = [x["exercise_id"] for x in matches]
    names = {x["exercise_id"]: x["name"] + " · " + x["equipment_type"] for x in matches}
    selected = st.selectbox("选择动作", ids, format_func=names.get, key=key + "_choice")
    item = next(x for x in matches if x["exercise_id"] == selected)
    if st.button("取消收藏" if item["favorite"] else "收藏动作", key=key + "_favorite"):
        svc.favorite(selected, not item["favorite"])
        st.rerun()
    return item


def _condition_form(svc, exercise, key, existing=None):
    old = existing or {}
    compatible = [
        x for x in svc.list_equipment() if x["equipment_type"] == exercise["equipment_type"]
    ]
    labels = {x["id"]: x["label"] for x in compatible}
    choices = [None, *labels]
    chosen = old.get("equipment_instance_id")
    instance = st.selectbox(
        "实际器械",
        choices,
        index=choices.index(chosen) if chosen in choices else 0,
        format_func=lambda x: labels.get(x, "未选择"),
        key=key + "_instance",
    )
    label = st.text_input("新器械名称（如健身房靠窗史密斯）", key=key + "_new_machine")
    loads = st.text_input("器械可用档位（可选，逗号分隔）", key=key + "_available_loads")
    source = st.text_input("档位依据（用户确认或厂家说明，可选）", key=key + "_step_source")
    bases = sorted(LOAD_BASES)
    selected_basis = old.get("load_basis") or exercise.get("default_load_basis", "unknown")
    basis = st.selectbox(
        "重量口径",
        bases,
        index=bases.index(selected_basis),
        format_func=LOAD_LABELS.get,
        key=key + "_basis",
    )
    if st.button("添加器械", key=key + "_add_machine"):

        def create():
            config = {}
            if loads.strip():
                config = {
                    "available_loads": [numeric(x.strip(), "档位") for x in loads.split(",")],
                    "step_basis": basis,
                    "step_source": source.strip(),
                }
            return svc.create_equipment(label, exercise["equipment_type"], configuration=config)

        if _act(create):
            st.rerun()
    confirmed = st.checkbox(
        "我确认上述重量口径", value=bool(old.get("load_basis_confirmed")), key=key + "_confirmed"
    )
    sides = ["unknown", "both", "left", "right", "not_applicable"]
    side = st.selectbox(
        "侧别", sides, index=sides.index(old.get("side") or "unknown"), key=key + "_side"
    )
    semantics = ["unknown", "simultaneous", "per_limb", "alternating_total", "not_applicable"]
    reps = st.selectbox(
        "次数含义",
        semantics,
        index=semantics.index(old.get("repetition_semantics") or "unknown"),
        key=key + "_repmeaning",
    )
    rom = st.text_input(
        "动作幅度（未知可留空）", value=old.get("rom_protocol") or "", key=key + "_rom"
    )
    previous_settings = old.get("settings") or {}
    previous_text = previous_settings.get(
        "description",
        json.dumps(previous_settings, ensure_ascii=False) if previous_settings else "",
    )
    settings = st.text_input(
        "角度、座椅、握法等设置（不适用可填不适用）", value=previous_text, key=key + "_settings"
    )
    settings_ok = st.checkbox(
        "已确认影响比较的器械和动作设置",
        value=bool(old.get("settings_confirmed")),
        key=key + "_settings_ok",
    )
    old_protocol = old.get("reference_protocol")
    protocol_note = old.get("reference_protocol_note") or (
        old_protocol if isinstance(old_protocol, str) else ""
    )
    structured = old_protocol if isinstance(old_protocol, dict) else {}
    protocol = {}
    with st.expander("结构化参考测量协议（未知字段留空）"):
        st.caption(
            "协议标识和版本与策略、用力、节奏及休息规则共同定义一次测量任务；说明文字不替代这些字段。修改规则请更新版本。"
        )
        for field, suffix, label in (
            ("protocol_id", "id", "协议标识"),
            ("version", "version", "协议版本"),
            ("reference_policy_id", "policy", "参考组选择规则"),
            ("effort_protocol", "effort", "用力终止规则"),
            ("tempo", "tempo", "动作节奏规则"),
            ("rest_protocol", "rest", "参考组前休息规则"),
        ):
            value = st.text_input(
                label, value=structured.get(field) or "", key=key + "_protocol_" + suffix
            )
            protocol[field] = value.strip() or None
    note = st.text_input(
        "参考协议备注（可选，不作为可比性条件）",
        value=protocol_note,
        key=key + "_protocol",
    )
    symmetric = (
        st.checkbox(
            "两侧对称配重", value=bool(old.get("symmetric_loading")), key=key + "_symmetric"
        )
        if basis == "plates_per_side_kg"
        else None
    )
    bar = (
        st.text_input(
            "已知有效杆重 kg（未知留空）",
            value=""
            if old.get("effective_bar_mass_kg") is None
            else str(old["effective_bar_mass_kg"]),
            key=key + "_bar",
        )
        if basis == "plates_per_side_kg"
        else ""
    )
    count = (
        st.text_input(
            "实际使用哑铃只数（未知留空，不自动乘二）",
            value="" if old.get("implement_count") is None else str(old["implement_count"]),
            key=key + "_implement_count",
        )
        if basis == "per_dumbbell_kg"
        else ""
    )
    return {
        **old,
        "equipment_instance_id": instance,
        "load_basis": basis,
        "load_basis_confirmed": confirmed,
        "side": side,
        "repetition_semantics": reps,
        "rom_protocol": rom or None,
        "settings": previous_settings
        if settings == previous_text
        else ({"description": settings} if settings else {}),
        "settings_confirmed": settings_ok,
        "symmetric_loading": symmetric,
        "effective_bar_mass_kg": numeric(bar, "杆重"),
        "implement_count": numeric(count, "哑铃只数", integer=True),
        "reference_protocol": protocol if any(protocol.values()) else None,
        "reference_protocol_note": note or None,
    }


def _targets(key):
    count = st.number_input("计划组数", min_value=1, value=1, key=key + "_count")
    low = st.text_input("目标次数下限（可留空）", key=key + "_low")
    high = st.text_input("目标次数上限（可留空）", key=key + "_high")
    rir = st.text_input("目标 RIR（可留空）", key=key + "_rir")
    rest = st.text_input("目标休息秒数（可留空）", key=key + "_rest")
    return {
        "sets": [
            {
                "set_type": "work",
                "reps_min": int(low) if low else None,
                "reps_max": int(high) if high else None,
                "rir": float(rir) if rir else None,
                "rest_seconds": float(rest) if rest else None,
            }
            for _ in range(int(count))
        ]
    }


def _set_editor(repo, svc, row, instance, key_prefix="set"):
    identity = row["set_uuid"] or row["id"]
    prefix = f"{key_prefix}_{identity}"
    if row.get("deleted_at"):
        st.caption(f"第 {row['set_number']} 组已删除；可在历史事件中撤销。")
        return
    st.markdown(f"**第 {row['set_number']} 组 · {row.get('completion_state') or '历史记录'}**")
    planned = row.get("planned") or {}
    if planned:
        st.caption(
            f"目标 {planned.get('reps_min') or '—'}–{planned.get('reps_max') or '—'} 次；RIR {planned.get('rir') if planned.get('rir') is not None else '未设'}"
        )
    mode = instance["condition"]["measurement_mode"]
    baseline = _bind_set_form(row, mode, prefix)
    revision = baseline["revision"]
    fields = [
        ("load_value", "重量 / 刻度"),
        (
            {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}[mode],
            {"repetitions": "实际完成次数", "duration": "持续秒数", "distance": "距离（米）"}[mode],
        ),
        ("rir", "实际 RIR（未知留空）"),
    ]
    for field, label in fields:
        key = prefix + "_" + field
        st.text_input(
            label,
            value="" if row.get(field) is None else str(row[field]),
            key=key,
            on_change=_draft_change,
            args=(str(repo.path), identity, revision, key, field, prefix, mode),
        )
    unit = st.selectbox(
        "单位",
        ["kg", "lb", "stack_level", "level"],
        index=["kg", "lb", "stack_level", "level"].index(row.get("load_unit") or "kg"),
        key=prefix + "_unit",
        on_change=_draft_change,
        args=(str(repo.path), identity, revision, prefix + "_unit", "load_unit", prefix, mode),
    )
    stop = st.selectbox(
        "停止原因",
        list(STOP_LABELS),
        format_func=STOP_LABELS.get,
        index=list(STOP_LABELS).index(row.get("stop_reason") or "unknown"),
        key=prefix + "_stop",
        on_change=_draft_change,
        args=(str(repo.path), identity, revision, prefix + "_stop", "stop_reason", prefix, mode),
    )
    kind = st.selectbox(
        "组类型",
        ["work", "warmup", "assessment", "other"],
        key=prefix + "_type",
        index=["work", "warmup", "assessment", "other"].index(row.get("set_type") or "work"),
    )
    quality = st.selectbox(
        "动作质量",
        [None, "acceptable", "technique_limited", "unknown"],
        format_func=lambda x: {
            None: "未记录",
            "acceptable": "达到本次动作要求",
            "technique_limited": "技术限制",
            "unknown": "无法判断",
        }[x],
        key=prefix + "_quality",
        index=[None, "acceptable", "technique_limited", "unknown"].index(row.get("quality_status")),
    )
    with st.expander("余力、量表、体重与助力"):
        rir_qualifier = st.selectbox(
            "RIR 记录含义",
            [None, "exact", "at_least"],
            format_func=lambda x: {None: "未注明", "exact": "估计为该值", "at_least": "至少该值"}[
                x
            ],
            index=[None, "exact", "at_least"].index(row.get("rir_qualifier")),
            key=prefix + "_rir_qualifier",
        )
        rpe = st.text_input(
            "逐组 RPE（可空）",
            value="" if row.get("rpe") is None else str(row["rpe"]),
            key=prefix + "_rpe",
        )
        scale = st.selectbox(
            "逐组 RPE 量表",
            [None, "cr10", "borg6_20", "rir_rpe10"],
            index=[None, "cr10", "borg6_20", "rir_rpe10"].index(row.get("rpe_scale")),
            key=prefix + "_rpe_scale",
        )
        additional = {}
        for field, label in (
            ("body_mass_kg", "体重 kg"),
            ("added_load_kg", "额外负重 kg"),
            ("assistance_value", "独立记录助力大小"),
            ("duration_s", "实际持续秒数"),
            ("distance_m", "实际距离米"),
            ("rest_recorded_s", "主动记录的组前休息秒数"),
            ("rest_recorded_method", "主动休息记录方法（如秒表或回忆）"),
        ):
            if field in {x[0] for x in fields}:
                continue
            additional[field] = st.text_input(
                label + "（未知留空）",
                value="" if row.get(field) is None else str(row[field]),
                key=prefix + "_extra_" + field,
            )
        pain = st.selectbox(
            "此组疼痛/不适",
            [None, True, False],
            format_func=lambda x: {None: "未记录", True: "有", False: "明确没有"}[x],
            index=[None, True, False].index(
                None if row.get("pain_flag") is None else bool(row["pain_flag"])
            ),
            key=prefix + "_pain",
        )
        st.caption(
            f"由相邻实际端点派生的组前休息：{row.get('rest_actual_s') if row.get('rest_actual_s') is not None else '未知'} 秒。主动记录与派生值分开保存。"
        )
    with st.expander("时间、特殊组和补充信息"):
        started = st.text_input(
            "实际开始时间（含时区）", value=row.get("started_at") or "", key=prefix + "_start"
        )
        ended = st.text_input(
            "实际结束时间（补录时填写）", value=row.get("ended_at") or "", key=prefix + "_end"
        )
        relation = st.selectbox(
            "组间关系",
            [None, "drop", "superset"],
            format_func=lambda x: {None: "普通组", "drop": "递减组", "superset": "超级组"}[x],
            key=prefix + "_relation",
            index=[None, "drop", "superset"].index(row.get("relation_kind")),
        )
        parent_set = st.text_input(
            "递减组的前序组 UUID（可空）",
            value=row.get("parent_set_uuid") or "",
            key=prefix + "_parent_set",
        )
        relation_id = st.text_input(
            "关联组名称", value=row.get("relation_group_id") or "", key=prefix + "_relation_id"
        )
        note = st.text_input(
            "动作质量 / 不适备注", value=row.get("quality_note") or "", key=prefix + "_note"
        )
        st.caption("参考组必须在完成前指定；不事后选择表现最好的一组。")
        if row.get("reference_set"):
            st.caption("已预先指定参考组")
        elif row.get("completion_state") in {"draft", "in_progress"}:
            if st.button("将这组预先指定为参考组", key=prefix + "_reference"):
                saved = _act(
                    svc.edit_set, identity, {"reference_set": True}, base_revision=revision
                )
                if saved:
                    _accept_set_form(saved, prefix, mode, {"reference_set"})
                    st.rerun()
    updates = {field: st.session_state[prefix + "_" + field] or None for field, _ in fields}
    updates.update(
        load_unit=unit,
        stop_reason=stop,
        set_type=kind,
        relation_kind=relation,
        relation_group_id=relation_id or None,
        parent_set_uuid=parent_set or None,
        quality_note=note or None,
        quality_status=quality,
        rir_qualifier=rir_qualifier,
        rpe=rpe or None,
        rpe_scale=scale,
        pain_flag=pain,
        **{k: v or None for k, v in additional.items()},
    )
    if st.button("保存字段更正", key=prefix + "_save_fields"):
        updates.update(started_at=started or None, ended_at=ended or None)
        dirty = _form_dirty(prefix, baseline)
        patch = {key: value for key, value in updates.items() if key in dirty}
        if patch:
            saved = _act(svc.edit_set, identity, patch, base_revision=revision)
            if saved:
                _accept_set_form(saved, prefix, mode, patch)
                st.rerun()
        else:
            st.info("没有修改实际字段；当前记录保持不变。")
    if row.get("completion_state") in {"draft", "in_progress"}:
        with st.expander("本组目标（与实际完成分开）"):
            target_low = st.text_input(
                "本组目标次数下限",
                value="" if planned.get("reps_min") is None else str(planned["reps_min"]),
                key=prefix + "_target_low",
            )
            target_high = st.text_input(
                "本组目标次数上限",
                value="" if planned.get("reps_max") is None else str(planned["reps_max"]),
                key=prefix + "_target_high",
            )
            target_rir = st.text_input(
                "本组目标 RIR",
                value="" if planned.get("rir") is None else str(planned["rir"]),
                key=prefix + "_target_rir",
            )
            if st.button("保存本组目标", key=prefix + "_target_save"):
                saved = _act(
                    svc.update_set_target,
                    identity,
                    {
                        **planned,
                        "reps_min": target_low or None,
                        "reps_max": target_high or None,
                        "rir": target_rir or None,
                    },
                    base_revision=revision,
                )
                if saved:
                    _accept_set_form(
                        saved, prefix, mode, {"planned.reps_min", "planned.reps_max", "planned.rir"}
                    )
                    st.rerun()
    for label, state in [
        ("开始这一组", "in_progress"),
        ("确认完成", "completed"),
        ("失败尝试 / 中止", "aborted"),
        ("跳过", "skipped"),
    ]:
        if st.button(label, key=prefix + "_" + state):
            dirty = _form_dirty(prefix, baseline)
            updates = {key: value for key, value in updates.items() if key in dirty}
            updates["completion_state"] = state
            updates["started_at"] = started or (_now() if state == "in_progress" else None)
            updates["ended_at"] = ended or (_now() if state in {"completed", "aborted"} else None)
            result = _act(
                svc.edit_set,
                identity,
                updates,
                base_revision=revision,
                event_id=str(uuid4()),
            )
            if result:
                _accept_set_form(result, prefix, mode, updates)
                st.rerun()
    if st.button("复制为下一组草稿", key=prefix + "_copy"):
        actual = {
            field: row.get(field)
            for field in ("load_value", "load_unit", "reps", "duration_s", "distance_m")
        }
        actual["completion_state"] = "draft"
        if _act(svc.add_set, instance["id"], actual, planned):
            st.rerun()
    if st.button("删除这一组（可撤销）", key=prefix + "_delete"):
        if _act(svc.delete_set, identity, base_revision=revision):
            st.rerun()


def render_training(repo):
    svc = TrainingService(repo)
    st.subheader("我的训练")
    st.caption("先记录实际完成；目标和上次值始终需要确认。无手表或 AI 也能记录。")
    if notice := st.session_state.pop("training_notice", None):
        st.warning(notice)
    with st.expander("离线训练记录器"):
        st.download_button(
            "下载可离线打开的记录器",
            recorder_html(),
            file_name="HealthZIP_离线记录器.html",
            mime="text/html",
        )
        st.caption(
            "先连接本机接收器并缓存模板。独立文件可断网刷新，草稿保存在本浏览器；恢复连接后按原请求ID同步。手机填电脑局域网地址和token；普通局域网页面断网重开不保证可用。"
        )
    pages = st.tabs(["开始 / 续记", "模板", "动作维护", "历史 / 冲突"])
    with pages[1]:
        _templates(svc)
    with pages[2]:
        _catalog(svc)
    with pages[3]:
        _history(svc)
    with pages[0]:
        templates = svc.list_templates()
        labels = {x["id"]: x["name"] for x in templates}
        selected = st.selectbox(
            "选择模板或临时训练",
            [None, *labels],
            format_func=lambda x, labels=labels: labels.get(x, "临时训练"),
            key="start_template",
        )
        name = st.text_input("本次训练名称", key="start_name")
        if st.button("开始训练", key="training_start", type="primary"):
            result = _act(svc.start_session, name, template_id=selected)
            if result:
                st.session_state["active_training"] = result["id"]
                for key in (
                    "session_feedback",
                    "session_srpe",
                    "session_minutes",
                    "timer_target",
                    "timer_extension",
                ):
                    st.session_state.pop(key, None)
                st.rerun()
        sessions = svc.list_sessions()
        active = [
            x for x in sessions if x.get("session_status") in {"draft", "in_progress", "paused"}
        ]
        if active:
            labels = {x["id"]: f"{x['session_date']} · {x['name']} · #{x['id']}" for x in active}
            identity = st.selectbox(
                "继续未结束训练", list(labels), format_func=labels.get, key="resume_training"
            )
            _session(repo, svc, svc.get_session(identity))


def _templates(svc):
    templates = svc.list_templates()
    labels = {x["id"]: x["name"] for x in templates}
    selected = st.selectbox(
        "维护模板",
        [None, *labels],
        format_func=lambda x, labels=labels: labels.get(x, "新建模板"),
        key="edit_template",
    )
    current = svc.get_template(selected) if selected else None
    name = st.text_input(
        "模板名称", value=current["name"] if current else "", key=f"template_name_{selected}"
    )
    item = _selector(svc, "template_selector")
    if item:
        try:
            condition = _condition_form(svc, item, "template_condition")
            targets = _targets("template_targets")
        except ValueError:
            st.info("请输入有效的数字目标。")
            return
        if st.button("加入模板并保存", key="template_save"):
            items = list(current["items"]) if current else []
            items.append(
                {"exercise_id": item["exercise_id"], "condition": condition, "targets": targets}
            )
            result = (
                _act(svc.update_template, selected, name, items, base_revision=current["version"])
                if current
                else _act(svc.create_template, name, items)
            )
            if result:
                st.success("模板已保存。")
    if current:
        for i, entry in enumerate(current["items"]):
            st.write(
                f"{i + 1}. {svc.get_exercise(entry['exercise_id'])['name']} · {len(entry.get('targets', {}).get('sets', []))} 组"
            )
            with st.expander(f"修改第 {i + 1} 个动作的目标与顺序"):
                revised = st.data_editor(
                    entry.get("targets", {}).get("sets", []),
                    num_rows="dynamic",
                    key=f"template_targets_edit_{selected}_{i}",
                )
                if st.button("保存目标修改", key=f"template_targets_save_{selected}_{i}"):
                    items = list(current["items"])
                    items[i] = {**entry, "targets": {**entry.get("targets", {}), "sets": revised}}
                    if _act(
                        svc.update_template, selected, name, items, base_revision=current["version"]
                    ):
                        st.rerun()
                try:
                    condition = _condition_form(
                        svc,
                        svc.get_exercise(entry["exercise_id"], entry.get("definition_version")),
                        f"template_condition_edit_{selected}_{i}",
                        entry.get("condition"),
                    )
                except ValueError as exc:
                    st.info(str(exc))
                else:
                    if st.button("保存模板动作条件", key=f"template_condition_save_{selected}_{i}"):
                        items = list(current["items"])
                        items[i] = {**entry, "condition": condition}
                        if _act(
                            svc.update_template,
                            selected,
                            name,
                            items,
                            base_revision=current["version"],
                        ):
                            st.rerun()
                if i and st.button("上移", key=f"template_up_{selected}_{i}"):
                    items = list(current["items"])
                    items[i - 1], items[i] = items[i], items[i - 1]
                    if _act(
                        svc.update_template, selected, name, items, base_revision=current["version"]
                    ):
                        st.rerun()
            if st.button("移除此动作", key=f"template_remove_{selected}_{i}"):
                _act(
                    svc.update_template,
                    selected,
                    name,
                    [x for j, x in enumerate(current["items"]) if i != j],
                    base_revision=current["version"],
                )
                st.rerun()
        copy_name = st.text_input("复制后的名称", key="template_copy_name")
        if st.button("复制模板"):
            if _act(svc.copy_template, selected, copy_name):
                st.rerun()


def _catalog(svc):
    with st.form("new_custom_exercise"):
        name = st.text_input("我的动作名称")
        mode = st.selectbox("记录模式", ["repetitions", "duration", "distance"])
        equipment = st.text_input("器械类别", "other")
        basis = st.selectbox("自定义动作负荷口径", sorted(LOAD_BASES), format_func=LOAD_LABELS.get)
        submitted = st.form_submit_button("创建自定义动作")
    if submitted:
        if _act(svc.create_exercise, name, mode, equipment, basis):
            st.success("动作已保存。肌群映射保持待审核。")
    item = _selector(svc, "catalog_maintenance")
    if item:
        alias = st.text_input("添加我的别名", key="new_alias")
        if st.button("保存别名"):
            _act(svc.add_alias, item["exercise_id"], alias)
        if item.get("custom"):
            rename = st.text_input("修改显示名称", value=item["name"], key="rename_custom")
            if st.button("保存名称"):
                _act(
                    svc.update_exercise,
                    item["exercise_id"],
                    {"name_zh": rename},
                    base_revision=item["revision"],
                )
            with st.expander("修改自定义动作的测量定义（创建新版本）"):
                mode = st.selectbox(
                    "新的记录模式",
                    ["repetitions", "duration", "distance"],
                    index=["repetitions", "duration", "distance"].index(item["recording_mode"]),
                    key="custom_edit_mode",
                )
                equipment = st.text_input(
                    "新的器械类别", value=item["equipment_type"], key="custom_edit_equipment"
                )
                basis = st.selectbox(
                    "新的负荷口径",
                    sorted(LOAD_BASES),
                    index=sorted(LOAD_BASES).index(item["default_load_basis"]),
                    format_func=LOAD_LABELS.get,
                    key="custom_edit_basis",
                )
                if st.button("保存测量定义新版本"):
                    if _act(
                        svc.update_exercise,
                        item["exercise_id"],
                        {
                            "recording_mode": mode,
                            "equipment_type": equipment,
                            "default_load_basis": basis,
                        },
                        base_revision=item["revision"],
                    ):
                        st.rerun()
        st.caption("显示分类与专业肌群映射独立。未审核关系不会自动折算有效组数。")


def _instance_controls(svc, instance):
    key = "instance_" + instance["id"]
    if instance.get("replaced_by_instance_id"):
        st.caption("此动作已替换；已完成记录与原条件仍保留。")
        return
    with st.expander("维护本次动作条件"):
        try:
            revised = _condition_form(
                svc, instance["exercise"], key + "_condition", instance["condition"]
            )
        except ValueError as exc:
            st.info(str(exc))
        else:
            if st.button("保存本次条件（执行后须新建条件）", key=key + "_condition_save"):
                if _act(
                    svc.update_condition,
                    instance["id"],
                    revised,
                    base_revision=instance["revision"],
                ):
                    st.rerun()
    with st.expander("替换动作或改用另一器械条件"):
        st.caption("替换保留此前已完成组；未执行组记为跳过，不把旧表现当新动作表现。")
        selected = _selector(svc, key + "_replacement")
        if selected:
            try:
                condition = _condition_form(svc, selected, key + "_replacement_condition")
                targets = _targets(key + "_replacement_targets")
            except ValueError as exc:
                st.info(str(exc))
            else:
                reason = st.text_input("替换原因", key=key + "_replacement_reason")
                if st.button("确认替换并保留原记录", key=key + "_replace"):
                    if _act(
                        svc.replace_exercise,
                        instance["id"],
                        selected["exercise_id"],
                        condition,
                        reason=reason,
                        targets=targets,
                        base_revision=instance["revision"],
                    ):
                        st.rerun()


def _session(repo, svc, session):
    st.write(f"{session['name']} · 已确认完成 {session['completed_sets']} 组")
    with st.expander("训练前状态（可选）"):
        from healthzip.state_log import ANCHORS, save_state

        st.caption("这是本产品的记录问卷，不是已验证临床量表。留空表示未记录。")
        fatigue = st.selectbox(
            "当前总体疲劳",
            [None, 0, 1, 2, 3, 4],
            format_func=lambda x: "未回答" if x is None else ANCHORS[str(x)],
            key="pre_fatigue",
        )
        soreness = st.selectbox(
            "当前酸痛",
            [None, 0, 1, 2, 3, 4],
            format_func=lambda x: "未回答" if x is None else ANCHORS[str(x)],
            key="pre_soreness",
        )
        muscle = st.text_input("酸痛部位 / 侧别", key="pre_muscle")
        pain = st.selectbox(
            "疼痛或不适",
            [None, "reported", "denied", "unknown"],
            format_func=lambda x: {
                None: "未回答",
                "reported": "有",
                "denied": "明确没有",
                "unknown": "不确定",
            }[x],
            key="pre_pain",
        )
        impact = st.text_input("不适对动作的影响", key="pre_impact")
        if st.button("保存当前状态"):
            if _act(
                save_state,
                repo,
                fatigue=fatigue,
                soreness=soreness,
                pain=pain,
                muscle=muscle or None,
                movement_impact=impact or None,
            ):
                st.success("已保存观察和录入时间。它不会自动换算为重量或恢复总分。")
    with st.expander("添加动作", expanded=not session["exercises"]):
        item = _selector(svc, "session_selector")
        if item:
            try:
                condition = _condition_form(svc, item, "session_condition")
            except ValueError:
                st.info("杆重应为数字或留空。")
                return
            if st.button("添加到本次训练"):
                if _act(svc.add_exercise, session["id"], item["exercise_id"], condition):
                    st.rerun()
    for instance in session["exercises"]:
        if instance.get("deleted_at"):
            continue
        st.markdown("### " + instance["exercise"]["name"])
        st.caption(LOAD_LABELS.get(instance["condition"]["load_basis"], "未知口径"))
        _instance_controls(svc, instance)
        previous = svc.last_values(instance["id"])
        if previous["status"] == "available":
            st.write("上次同条件记录：", previous["suggested_actual"])
            st.caption("来源时间：" + str(previous.get("source_event_time")))
            if st.button("带入上次值为草稿", key="last_" + instance["id"]):
                if _act(svc.add_set, instance["id"], previous["suggested_actual"]):
                    st.rerun()
        else:
            st.info("同条件历史不足或条件尚未确认；仍可正常记录。")
        from healthzip.ui.recommendation_page import render_candidates

        render_candidates(repo, svc, session, instance)
        index = session["exercises"].index(instance)
        if index and st.button("将此动作上移", key="session_up_" + instance["id"]):
            ids = [x["id"] for x in session["exercises"] if not x.get("deleted_at")]
            pos = ids.index(instance["id"])
            ids[pos - 1], ids[pos] = ids[pos], ids[pos - 1]
            if _act(svc.reorder_exercises, session["id"], ids, base_revision=session["revision"]):
                st.rerun()
        if not instance.get("replaced_by_instance_id") and st.button(
            "新增一组", key="add_set_" + instance["id"]
        ):
            if _act(svc.add_set, instance["id"], {"load_unit": "kg"}):
                st.rerun()
        for row in instance["sets"]:
            _set_editor(repo, svc, row, instance)
        completed = [
            x
            for x in instance["sets"]
            if x.get("completion_state") == "completed" and not x.get("deleted_at")
        ]
        if completed and previous.get("suggested_actual"):
            delta = load_change(previous["suggested_actual"], completed[-1], instance["condition"])
            if delta["plates_total_change_kg"] is not None:
                st.write(f"两侧配重合计变化：{delta['plates_total_change_kg']:+g} kg")
                if delta["external_total_change_kg"] is None:
                    st.caption("有效杆重未知，未计算含杆总负荷或百分比。")
    with st.expander("休息与结束反馈"):
        target = st.text_input("本次休息目标秒数（留空为正计时）", key="timer_target")
        if st.button("开始休息计时"):
            if _act(svc.rest_timer, session["id"], "start", target_seconds=target or None):
                st.rerun()
        timer = session.get("rest_timer")
        if timer:
            st.write(timer)
            st.caption("计时提示不等于实际休息；实际休息由两组的真实结束/开始事件计算。")
            for label, action in (
                ("暂停计时", "pause"),
                ("继续计时", "resume"),
                ("跳过休息", "skip"),
            ):
                if st.button(label):
                    if _act(svc.rest_timer, session["id"], action):
                        st.rerun()
            extension = st.text_input("增加休息秒数", key="timer_extension")
            if st.button("延长休息"):
                if extension:
                    if _act(svc.rest_timer, session["id"], "extend", target_seconds=extension):
                        st.rerun()
        if st.button("继续训练"):
            _act(
                svc.update_session,
                session["id"],
                {"session_status": "in_progress"},
                base_revision=session["revision"],
            )
            st.rerun()
        if st.button("暂停训练"):
            _act(
                svc.update_session,
                session["id"],
                {"session_status": "paused"},
                base_revision=session["revision"],
            )
            st.rerun()
        note = st.text_area("本次反馈 / 未完成原因", key="session_feedback")
        srpe = st.text_input("整次训练主观用力（0–10，可留空）", key="session_srpe")
        minutes = st.text_input("整次训练时长（分钟，可留空）", key="session_minutes")
        if st.button("中断并保留记录"):
            if _act(
                svc.update_session,
                session["id"],
                {"session_status": "aborted", "ended_at": _now(), "feedback": {"notes": note}},
                base_revision=session["revision"],
            ):
                st.rerun()
        if st.button("结束训练并保存反馈"):

            def finish():
                duration = numeric(minutes, "训练时长分钟")
                return svc.end_session(
                    session["id"],
                    feedback={"notes": note},
                    session_rpe=srpe or None,
                    rpe_scale="cr10" if srpe else None,
                    duration_seconds=duration * 60 if duration is not None else None,
                    duration_protocol="user_elapsed_including_rest" if minutes else None,
                )

            result = _act(finish)
            if result:
                st.rerun()


def _exchange(svc):
    from healthzip.training.exchange import export_training, import_training, preview_import

    with st.expander("训练 CSV / JSON 导入导出"):
        st.caption(
            "预览明确字段与负荷口径；旧 CSV 的未知口径保持未知。导出含私人记录，只保存在本机。"
        )
        path = st.text_input("本机训练导入文件路径", key="training_import_path")
        if st.button("预览导入与字段", key="training_import_preview"):
            result = _act(preview_import, path)
            if result:
                st.session_state["training_import_preview_result"] = {
                    "path": path,
                    "preview": result,
                }
        saved = st.session_state.get("training_import_preview_result")
        if saved and saved["path"] == path:
            result = saved["preview"]
            st.write({k: v for k, v in result.items() if k != "sample_rows"})
            if result.get("sample_rows"):
                st.dataframe(result["sample_rows"], hide_index=True, use_container_width=True)
            if st.button("按此预览导入到本机", key="training_import_apply"):

                def apply():
                    if preview_import(path)["sha256"] != result["sha256"]:
                        raise ValueError("文件已改变，请重新预览")
                    return import_training(svc.repo, path)

                imported = _act(apply)
                if imported is not None:
                    st.write(imported)
        output = st.text_input(
            "导出路径", value=".local/exports/training.json", key="training_export_path"
        )
        format = st.selectbox("导出格式", ["json", "csv"], key="training_export_format")
        if st.button("导出全部训练", key="training_export_all"):
            exported = _act(export_training, svc.repo, output, format=format)
            if exported:
                st.success(f"已导出到 {exported}")


def _legacy_history(svc):
    rows = svc.legacy_records(include_deleted=True)
    if not rows:
        return
    with st.expander(f"旧格式原始训练记录（{len(rows)} 组）"):
        st.caption(
            "保留原始数值；负荷口径、完成状态和当时可用时间未知。分析中列出排除原因，不把它们补成已完成组或可比表现。没有会话的旧 CSV 仍保持没有会话。"
        )
        st.dataframe(
            [
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "session_id",
                        "set_date",
                        "exercise_name",
                        "weight_kg",
                        "reps",
                        "rir",
                        "load_basis",
                        "deleted_at",
                    )
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        identity = st.selectbox(
            "选择旧记录更正", [row["id"] for row in rows], key="legacy_edit_record"
        )
        row = next(x for x in rows if x["id"] == identity)
        key = f"legacy_{identity}"
        if row.get("deleted_at"):
            deletion = next(
                (
                    event
                    for event in reversed(svc.audit_events(str(identity)))
                    if event["action"] == "delete_set" and event["status"] == "applied"
                ),
                None,
            )
            if deletion and st.button("恢复旧记录", key=key + "_restore"):
                if _act(svc.undo_event, deletion["event_id"], base_revision=row["revision"]):
                    st.rerun()
            return
        changes = {}
        for field, label in (
            ("exercise_name", "原始动作名"),
            ("weight_kg", "原始 weight_kg（不代表已确认含杆总重）"),
            ("reps", "原始次数"),
            ("rir", "原始 RIR"),
            ("rpe", "原始 RPE（量表保持未知）"),
            ("notes", "备注"),
        ):
            value = st.text_input(
                label,
                value="" if row.get(field) is None else str(row[field]),
                key=key + "_" + field,
            )
            changes[field] = value or None
        if st.button("保存旧记录原始字段更正", key=key + "_save"):
            if _act(svc.edit_legacy_set, identity, changes, base_revision=row["revision"]):
                st.rerun()
        if st.button("删除旧记录（可撤销）", key=key + "_delete"):
            if _act(svc.delete_set, identity, base_revision=row["revision"]):
                st.rerun()


def _history(svc):
    _exchange(svc)
    _legacy_history(svc)
    _conflicts(svc)
    sessions = svc.list_sessions(include_deleted=True)
    if not sessions:
        st.info("尚无训练记录。")
        return
    labels = {x["id"]: f"{x['session_date']} · {x['name']} · #{x['id']}" for x in sessions}
    selected = st.selectbox("训练历史", list(labels), format_func=labels.get)
    detail = svc.get_session(selected)
    st.dataframe(
        [
            {
                k: x.get(k)
                for k in (
                    "set_uuid",
                    "exercise_name",
                    "completion_state",
                    "load_basis",
                    "load_value",
                    "reps",
                    "rir",
                    "stop_reason",
                    "deleted_at",
                )
            }
            for x in detail["sets"]
        ],
        use_container_width=True,
    )
    template_name = st.text_input("另存为模板名称")
    if st.button("按本次目标另存模板"):
        _act(svc.save_session_as_template, selected, template_name)
    with st.expander("历史逐组更正"):
        for instance in detail["exercises"]:
            for row in instance["sets"]:
                _set_editor(svc.repo, svc, row, instance, key_prefix="history")
    if detail.get("session_status") in {"completed", "aborted"}:
        from healthzip.ui.recommendation_page import render_candidates

        with st.expander("本次训练的建议与结束后反馈"):
            for instance in detail["exercises"]:
                render_candidates(
                    svc.repo, svc, detail, instance, allow_create=False, key_prefix="history_"
                )
    with st.expander("训练信息修订与删除"):
        title = st.text_input(
            "更正训练名称", value=detail["name"], key=f"history_session_name_{detail['id']}"
        )
        start = st.text_input(
            "更正训练开始时间（含时区）",
            value=detail.get("started_at") or "",
            key=f"history_session_start_{detail['id']}",
        )
        if st.button("保存训练信息"):
            if _act(
                svc.update_session,
                selected,
                {"name": title, "started_at": start},
                base_revision=detail["revision"],
            ):
                st.rerun()
        if not detail.get("deleted_at") and st.button("删除此训练（可撤销）"):
            if _act(svc.delete_session, selected, base_revision=detail["revision"]):
                st.rerun()
    events = [
        dict(x)
        for x in svc.conn.execute(
            "SELECT * FROM training_event WHERE user_id=? ORDER BY recorded_at DESC LIMIT 30",
            (svc.user_id,),
        )
    ]
    with st.expander("撤销与版本记录"):
        for event in events:
            st.caption(f"{event['recorded_at']} · {event['action']} · {event['status']}")
            if event["entity_type"] in {"set", "session"} and event["status"] == "applied":
                if st.button("撤销此操作", key="undo_" + event["event_id"]):
                    current = (
                        svc.get_set(event["entity_id"])
                        if event["entity_type"] == "set"
                        else svc.get_session(event["entity_id"])
                    )
                    _act(svc.undo_event, event["event_id"], base_revision=current["revision"])
                    st.rerun()


def _conflicts(svc):
    conflicts = [
        dict(x)
        for x in svc.conn.execute(
            "SELECT * FROM training_conflict WHERE user_id=? AND resolved_by_event_id IS NULL",
            (svc.user_id,),
        )
    ]
    for conflict in conflicts:
        st.warning("有冲突的修改；当前事实尚未被覆盖。")
        st.write("当前版本", json.loads(conflict["current_json"]))
        st.write("提交的更改", json.loads(conflict["proposed_json"]))
        choice = st.selectbox(
            "选择保留的版本",
            ["keep_current", "apply_proposed"],
            format_func=lambda x: {
                "keep_current": "保留当前事实",
                "apply_proposed": "应用提交的更改",
            }[x],
            key="conflict_choice_" + conflict["id"],
        )
        if st.button("确认解决冲突", key="conflict_resolve_" + conflict["id"]):
            if _act(svc.resolve_conflict, conflict["id"], choice=choice):
                st.rerun()
    with st.expander("离线事件与重试"):
        st.write(svc.list_outbox())
        if st.button("重试待发送事件"):
            st.write(svc.replay_outbox())
