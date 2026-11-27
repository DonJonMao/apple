# 下一轮只读线索（未纳入 r11）

本次 r11 固定后，两个子代理只读检查了 fresh c71358d profile 和调用路径，未改代码或运行重测量。下列内容是待验证候选，不是已兑现提速。

1. `science/engine.py` 的 REPORT 派生分支先以 normalized/window/retrospective/overlap=True 选择，随后本次 evaluate 又选相同输入，profile 确认该分支发生 3 次。同次 evaluate_all 的预选择及 inventory 选择可接入现有请求内选择缓存；四次 evaluate_all 理论另有 8 次重复。须完整复用 selected/excluded，不跨 global/scoped 或不同 overlap/window 复用。现有 profile 不能拆出这些具体行的节省秒数。
2. `analytics/body_questions.py::_strength_rows` 每条记录已算 daily_identity，分组后对未修改的 last 再算。在当前独立未知组夹具中，该边 20,000 次、累计 1.660 秒；可核对按条保留身份，不能把全部 15.617 秒 flatten_record 成本当成收益。
3. 冷复盘摘要的 `_summary_projection` 仍返回完整 result_json。applied 事件通常把同一完整快照写入 after_json/result_json；history_as_of 仅在 conflicted 状态使用 result.conflict_id。可先验证摘要专属 conflict_id 投影，保留事件、精确时间和冲突身份，其余生产回放不变。
4. 再评估嵌套 after.sets 投影：摘要消费 set_uuid/session_id/started_at/ended_at/completion_state/set_type/session_exercise_id/deleted_at；全部子项和顺序必须保留，不能预先筛掉 draft、删项或窗口外项。父 session 状态、session setdefault、session_exercise overwrite、undo、move 和冲突时态都要等价。SQL json_each 重建数组也有代价，不能未经测量认定收益。

既有 engine 已共享归一化输入、受限 context、选择和部分负荷计算；不要重复实现。SELECT * CTE 大 JSON 物化及驱动固定等待的猜测已被既有证据排除。这里只建议下一步能直接反证的最小候选，保留 15 秒报告、3 秒冷页面合同。
