"""Imported observation identities and permitted descriptive statistics."""

from healthzip.normalize import TYPE_MAP

# canonical type, user-facing title, aggregation, limitation
_SECTIONS = (
    (
        "心率与心肺",
        "W3",
        (
            ("heart_rate_bpm", "普通心率", "samples", "机会性测量只描述已记录样本。"),
            (
                "workout_heart_rate_bpm",
                "运动心率",
                "samples",
                "按实际运动区间关联；同负荷和运动类型才可比较。",
            ),
            (
                "resting_heart_rate_bpm",
                "日静息心率",
                "daily",
                "设备报告的日静息字段，与普通心率分开。",
            ),
            (
                "hrv_sdnn_ms",
                "心率变异性 SDNN",
                "daily",
                "日代表值等权；记录时段和测量条件会影响比较。",
            ),
            ("walking_heart_rate_bpm", "步行平均心率", "daily", "步速、路线与负荷会影响步行心率。"),
            (
                "heart_rate_recovery_1m",
                "一分钟心率恢复",
                "estimate",
                "恢复协议和运动负荷影响来源报告值的比较。",
            ),
            (
                "vo2_max_ml_kg_min",
                "来源报告 VO₂max",
                "estimate",
                "展示来源估计点，需结合运动条件与绝对表现。",
            ),
        ),
    ),
    (
        "睡眠与夜间生理",
        "W6",
        (
            (
                "sleep_stage",
                "睡眠事件、时长与分期",
                "sleep",
                "按同一来源的实际区间并集和结束日期归属。",
            ),
            ("respiratory_rate_bpm", "呼吸率", "samples", "用睡眠时段和测量情境区分稀疏样本。"),
            (
                "oxygen_saturation_fraction",
                "血氧饱和度",
                "samples",
                "零散血氧样本只能描述测量时刻。",
            ),
            (
                "sleeping_wrist_temperature_c",
                "睡眠腕温",
                "daily",
                "绝对腕部温度与相对设备基线的偏差分开。",
            ),
            (
                "sleep_breathing_disturbances",
                "睡眠呼吸紊乱",
                "estimate",
                "来源报告每小时结果；通知另列，临床 AHI 需另行测量。",
            ),
        ),
    ),
    (
        "活动与行动能力",
        "W7",
        (
            ("steps", "步数", "sum", "按同一来源的增量记录累计，记录天数不等于全天佩戴。"),
            (
                "distance_walking_running_m",
                "步行和跑步距离",
                "sum",
                "只累计同来源样本，运动摘要与活动环独立保留。",
            ),
            ("distance_cycling_m", "骑行距离", "sum", "骑行记录取决于活动机会。"),
            ("exercise_minutes", "运动分钟", "sum", "设备估计的运动分钟依据来源定义。"),
            ("stand_hour", "站立小时", "stand", "统计有达到站立条件记录的小时，未达标的记录另存。"),
            ("stand_minutes", "站立分钟", "sum", "站立时长与达标小时各自汇总。"),
            ("flights_climbed", "爬楼层数", "sum", "爬楼记录同时受楼梯机会影响。"),
            (
                "physical_effort_met",
                "活动强度 MET",
                "samples",
                "MET 是来源估计的活动强度，主观 RPE/RIR 单独记录。",
            ),
            (
                "six_minute_walk_m",
                "六分钟步行距离",
                "estimate",
                "估计与实际测试按来源方法分开；重复发布和重叠支持窗口不能作为独立测试。",
            ),
            ("stair_ascent_m_s", "上楼速度", "samples", "只比较上楼方向和相似楼梯条件。"),
            ("stair_descent_m_s", "下楼速度", "samples", "只比较下楼方向和相似楼梯条件。"),
            ("walking_speed_m_s", "步行速度", "samples", "测量受手机携带位置与行走情境影响。"),
            ("walking_step_length_m", "步长", "samples", "结合实际步速和携带位置比较。"),
            (
                "walking_double_support_fraction",
                "双支撑时间比例",
                "samples",
                "比较同条件下的双支撑时间占比。",
            ),
            (
                "walking_asymmetry_fraction",
                "步态不对称比例",
                "samples",
                "来源记录出现不对称步态的时间比例。",
            ),
            (
                "walking_steadiness_fraction",
                "步行稳定性",
                "estimate",
                "来源报告结果和稳定性通知分别保留。",
            ),
        ),
    ),
    (
        "体重、体组成与能量",
        "W5",
        (
            ("body_mass_kg", "体重", "daily", "同一测量条件的日代表值，保留每次称重日期。"),
            ("height_cm", "身高", "samples", "记录日期与来源保留，用于依赖身高的计算。"),
            (
                "body_fat_fraction",
                "体脂比例",
                "samples",
                "分仪器和方法比较，短期变化不能拆成肌肉增减。",
            ),
            ("lean_body_mass_kg", "瘦体重", "samples", "瘦体重包含水分及其他非脂肪组织。"),
            ("active_energy_kcal", "活动能量", "sum", "设备报告的能量受算法、活动及记录覆盖影响。"),
            ("basal_energy_kcal", "静息能量", "sum", "设备对静息能量的估计与实际代谢测量分开。"),
            (
                "dietary_energy_kcal",
                "已记录饮食能量",
                "intake",
                "仅计已记录摄入，部分餐次不能估全天缺口。",
            ),
            ("dietary_protein_g", "已记录蛋白质", "intake", "只描述已记录份量。"),
            ("dietary_carbohydrates_g", "已记录碳水化合物", "intake", "只描述已记录份量。"),
            ("dietary_fat_g", "已记录脂肪", "intake", "只描述已记录份量。"),
            ("dietary_water_ml", "已记录饮水", "intake", "未记饮水保持未知。"),
            ("dietary_caffeine_mg", "已记录咖啡因", "intake", "保留实际摄入时点和记录量。"),
        ),
    ),
    (
        "环境",
        "W6",
        (
            ("daylight_minutes", "日照时长", "sum", "手腕记录的时长和时点与眼部光剂量有别。"),
            (
                "environmental_audio_dba",
                "环境声音暴露",
                "sound",
                "按声能和时长汇总，未覆盖区间保持未知。",
            ),
            (
                "headphone_audio_dba",
                "耳机声音暴露",
                "sound",
                "耳机与环境声音分别计算等效连续 A 声级。",
            ),
        ),
    ),
    (
        "周期与症状",
        "W8",
        (
            ("menstrual_flow", "经期流量日志", "event", "只展示主动记录的类别与日期。"),
            ("intermenstrual_bleeding", "经间出血记录", "event", "呈现已报告的发生时间。"),
            ("cervical_mucus_quality", "宫颈黏液记录", "event", "保留观察类别，不推算周期相位。"),
            ("ovulation_test_result", "排卵测试记录", "event", "呈现来源报告的测试结果。"),
            (
                "menstrual_cramps",
                "经期腹痛日志（既有来源字段）",
                "event",
                "本字段的 Apple 官方定义未确认；只保留来源实际日志。",
            ),
            (
                "abdominal_cramps",
                "腹痛或腹部痉挛日志",
                "event",
                "实际记录症状，不由腹痛推断经期或原因。",
            ),
        ),
    ),
    (
        "设备通知",
        "E",
        (
            ("number_of_times_fallen", "已记录跌倒次数", "sum", "记录可能晚于事件；本人忽略的提示不写入，缺记录不能排除跌倒。"),
            (
                "sleep_apnea_event",
                "睡眠呼吸暂停通知",
                "event",
                "设备通知与睡眠呼吸紊乱值分别回顾。",
            ),
            ("high_hr_event", "高心率通知", "event", "仅展示已生成并实际导入的通知。"),
            ("low_hr_event", "低心率通知", "event", "只记录通知时间与来源。"),
            ("irregular_rhythm_event", "心律不齐通知", "event", "通知不构成临床诊断。"),
            ("walking_steadiness_event", "步行稳定性通知", "event", "保留设备报告的事件类别。"),
            ("environmental_audio_event", "环境声音通知", "event", "事件与连续暴露的计算分开。"),
            ("headphone_audio_event", "耳机声音通知", "event", "实际通知与覆盖时长分别回顾。"),
        ),
    ),
)
_UNITS = dict(TYPE_MAP.values())
_UNITS.update(workout_heart_rate_bpm="count/min", sleep_stage="min", stand_hour="h")
METRIC_CATALOG = {
    key: {
        "title": title,
        "theme": theme,
        "workflow": workflow,
        "kind": kind,
        "unit": _UNITS[key],
        "note": note,
        "canonical_type": key,
        "metric_id": "BODY-OBS-" + key,
    }
    for theme, workflow, items in _SECTIONS
    for key, title, kind, note in items
}


def definition(metric_id):
    spec = METRIC_CATALOG[metric_id.removeprefix("BODY-OBS-")]
    return {**spec, "uncertainty": spec["note"], "forbidden_inferences": [], "evidence_refs": []}


# The product's top-level body sections are shared by all observation consumers.
for _key, _spec in METRIC_CATALOG.items():
    if _spec["theme"] == "心率与心肺":
        _spec["theme"] = (
            "有氧"
            if _key
            in {
                "heart_rate_recovery_1m",
                "vo2_max_ml_kg_min",
                "walking_heart_rate_bpm",
                "workout_heart_rate_bpm",
            }
            else "心率"
        )
    elif _spec["theme"] == "睡眠与夜间生理":
        _spec["theme"] = "睡眠" if _key == "sleep_stage" else "夜间生理"
    elif _spec["theme"] == "体重、体组成与能量":
        _spec["theme"] = "体重"
    elif _spec["theme"] == "设备通知":
        _spec["theme"] = "健康与安全事件"
