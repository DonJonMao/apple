# v1.3 训练数据与运行接口

训练记录使用既有 `Repository.conn`，保存在原 SQLite 文件。公共动作目录、用户自定义动作、模板、训练事实和事件在该私有库内；不会写入公开文献索引。原有整数 session/set 主键保留，新记录增加稳定 UUID。模板目标和已完成事实分开。

## 最小使用示例

```python
from healthzip.db.repository import Repository
from healthzip.training import TrainingService, load_change

repo = Repository('.local/healthzip.sqlite3')
svc = TrainingService(repo)
equipment = svc.create_equipment('健身房史密斯 A', 'smith')
condition = {
    'equipment_instance_id': equipment['id'],
    'load_basis': 'plates_per_side_kg', 'load_basis_confirmed': True,
    'side': 'both', 'repetition_semantics': 'simultaneous',
    'rom_protocol': '用户确认的完整幅度',
    'settings': {'bench_angle_degrees': 30}, 'settings_confirmed': True,
    'symmetric_loading': True, 'effective_bar_mass_kg': None,
}
plan = svc.create_template('胸部计划', [{
    'exercise_id': 'psa.ex.smith_incline_press', 'condition': condition,
    'targets': {'sets': [{'set_type': 'work', 'reps_min': 8, 'reps_max': 10,
                          'rir': 2, 'rest_seconds': 120}]},
}])
session = svc.start_session(template_id=plan['id'])
draft = session['sets'][0]
assert session['completed_sets'] == 0
actual = svc.edit_set(draft['id'], {
    'completion_state': 'completed', 'load_value': 30, 'load_unit': 'kg',
    'reps': 10, 'rir': 2, 'stop_reason': 'plan_target',
    'quality_status': 'acceptable',
}, base_revision=draft['revision'], event_id='client-generated-real-set-event-uuid')
svc.end_session(session['id'], feedback={'notes': '按计划完成'},
                session_rpe=7, rpe_scale='cr10',
                duration_seconds=3600, duration_protocol='elapsed_wall_clock')
next_session = svc.start_session(template_id=plan['id'])
last = svc.last_values(next_session['exercises'][0]['id'])
assert last['suggested_actual']['completion_state'] == 'draft'
assert next_session['completed_sets'] == 0
next_actual = svc.edit_set(next_session['sets'][0]['id'], {
    'completion_state': 'completed', 'load_value': 32.5, 'load_unit': 'kg',
    'reps': 8, 'rir': 2, 'stop_reason': 'plan_target',
}, base_revision=1)
change = load_change(actual, next_actual, condition)
assert change['plates_total_change_kg'] == 5
assert change['external_total_change_kg'] is None  # 有效杆重未知
repo.close()
```

示例中的目标由用户选择；2 RIR、120 秒并非系统生理默认值。实际质量必须独立确认，备注不自动变成 `acceptable`。没有计划时 `start_session()` 立即创建临时训练；`add_exercise()` 后可记录任意实际值。缺目标不会阻止记录。

## 记录与修订

- `create_exercise(name, recording_mode, equipment_type, load_basis)` 创建用户私有动作；动作缺少理论支持仍可记录。`search_exercises()` 支持名称/别名、分类、器械、模式、收藏、最近、自定义筛选。
- `create_template/update_template/copy_template` 保存不可变模板版本。开始训练冻结当时版本；后改模板不会重写过去训练。`save_session_as_template` 只复制已明确的目标，不把实际失败/实际 RIR 当下次目标。
- `add_set()` 默认为 draft；`edit_set(...completion_state='completed')` 才确认完成。失败尝试为 aborted，零次允许保留；热身和工作组、递减/超级组关联分别存储。
- `update_set_target` 只修改未完成组的明确目标；`update_condition` 只在动作尚无执行记录时修改条件。`replace_exercise` 保留已完成事实和原条件，将未执行组标为 skipped，记录替换原因并新建条件和目标；`reorder_exercises` 仅调整本次动作顺序。页面提供这些入口，不需要直接编辑 JSON。
- 参考组通过完成前的独立操作指定，保存 `reference_declared_at`。完成后指定、或在同一请求中同时指定并完成，都会拒绝。原始备注不自动解释为合格动作质量。
- `event_id` 标识请求；`set_uuid` 标识真实组。连续两个相同重量/次数组要用两个事件 ID；同请求重试继续用原 ID和原参数，不增组。`base_revision` 不匹配会保存可见冲突，原事实不覆盖。`resolve_conflict` 支持保留现状、采用提议、显式字段合并。
- `delete_set/delete_session` 写入 tombstone；`undo_event` 创建新修订。历史依据保留。记录变更使派生缓存失效、既有建议标记 stale，而不改其冻结输入；`pending_invalidations/mark_recomputed` 管理重算。
- `queue_event` 先把请求存本地 outbox；进程重启后 `replay_outbox` 可重试，失败保留原因。该队列不承诺无服务器时浏览器能自动持久化网页编辑，也不实现云同步；服务端收到的草稿即落盘，离线客户端应先以稳定 ID 保留事件再重发。
- `history_as_of(cutoff_time=...,include_incomplete=True)` 重放截止前已知修订，供指标各自选择完成/失败/草稿分母；不把补录时间当训练时间，不用未来修订。`sessions_as_of` 提供同样可用时间约束下的整次 RPE、时长和反馈。

旧版本和旧 CSV 的行仍可在“历史 / 冲突 → 旧格式原始训练记录”查看、更正原始字段、删除与撤销。`legacy_records()` 返回当前原始库存，不声称重建了过去可见性；`edit_legacy_set` 不把未知口径或未知完成状态变成已知。无所属会话的旧 CSV 保持 `session_id=None`。统一分析列出它们的来源 ID、待确认数量和排除原因，避免默默消失或伪造可比表现。

## 口径与比较

唯一规范 `load_basis`：`external_total_kg / plates_per_side_kg / per_dumbbell_kg / dumbbells_total_kg / single_implement_kg / machine_setting / bodyweight_no_external / added_load_kg / assistance_setting / band_configuration / unknown`。kg/lb 转换采用定义常数 0.45359237，不是生理参数。

单边片重只有确认双侧对称才能得到两侧片重之和；有效杆重未知不产生含杆总负荷或百分比。每只哑铃不暗中乘二。器械刻度不视为跨设备同一真实力。体重/额外负重/助力分别保存，不用体重减助力制造肌肉负荷。等长以秒、搬运以米为测量模式，不直接计算次数 e1RM。

比较条件包括用户、动作定义版本、器械实例、负荷口径、侧别、次数语义、幅度、关键设置以及显式测量协议。未知条件返回 `condition_key=None`，不是通配符。两个同型号器械仍有不同实例 ID。目标、计划版本和显示名称不进入物理比较键。自定义动作只改标签保持定义版本，改测量含义创建新版本；编辑 revision 独立递增。

46 个原创动作种子只用于导航。肌群参与草稿保持 unreviewed；不能把导航分类转换为定量有效组数。用户别名不自动合并两个动作；`mapping_preview/declare_mapping/revoke_mapping` 留下显式关联、差异和可撤销记录，原事实及不可比条件保持可查。

## 休息与反馈

`rest_timer(session_id, action, target_seconds=None)` 支持 start/pause/resume/extend/skip，时间锚点落盘，返回页面不会归零；系统时钟倒退显示异常。未设目标使用经过时间。倒计时到零不等于实际开练；`rest_actual_s` 只有可靠的前组结束与后组开始事件才计算。

整次 sRPE 单独填报 `session_rpe/session_rpe_scale`；时长须声明 `duration_protocol`。未提供这些输入时不以组 RPE 中位数或配重×次数代替整次 sRPE 负荷。

`record_recommendation` 冻结数据截止点、数据/理论/规则版本、候选改变、验证协议和输入来源。`recommendation_feedback` 留存采纳/修改/拒绝、实际执行、未执行原因和结果；计划不会因建议自动改变。旧建议输入不能重写，重新计算使用新 candidate_id。

新增候选与执行反馈会递增数据版本并使报告缓存失效，但不会将候选自身标记为过期；后续训练事实更改才使相关冻结依据需要复核。相同候选或反馈请求重试不会重复增加版本。持久化 outbox 和浏览器批次遇到失败或冲突即停止后续事件；解决冲突后再继续重试。

## CSV / JSON 交换

界面“历史 / 冲突 → 训练 CSV / JSON 导入导出”提供本机路径预览，显示字段、口径、前 20 组与文件 SHA256。正式导入前再次检查哈希，文件改变须重新预览。CLI 等价入口：

```bash
PYTHONPATH=src .venv/bin/python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-import .local/incoming/training.json --preview
PYTHONPATH=src .venv/bin/python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-import .local/incoming/training.json --source my_training_export
PYTHONPATH=src .venv/bin/python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-export-all .local/exports/training.json
PYTHONPATH=src .venv/bin/python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-export-all .local/exports/training.csv --format csv
```

`training.exchange.preview_import/import_training/export_training` 为同一实现。JSON 保存会话、组、动作定义版本、器械、模板快照、计划槽和源审计；原单会话 `TrainingService.export_session` 也包含新库恢复所需依赖。CSV 的实际值为独立列，条件、目标和会话元数据为明确的 JSON 列；空会话、未开始动作也保留。旧格式记录导出 CSV 时另写 `<文件名>.csv.legacy.json`，两份文件都应保留；旧记录从该伴随 JSON 单独导入。需要单文件完整交接时使用 JSON。

v1.3 使用稳定 UUID、源版本和内容哈希识别重复请求，不按动作名合并。源更正可传播明确的 null；源删除和撤销删除保留事件。遇到本地并发更正保存完整冲突，选择保留当前或采用来源后重复导入不会重新打开同一冲突。某一会话含非法组时，该会话回滚并报告原因，其他独立会话继续处理。首次导入的 `available_at` 为本机导入时刻，源端时间和源声明保存在审计原文；外部参考组声明不自动升级为本机可验证的预声明。

## 升级、备份与恢复

运行时由 `Repository._migrate_schema()` 调用 `migrate_training(conn)`。迁移以 SAVEPOINT 执行逐条 DDL，异常整个 v1.3 增量回滚，可重跑；不通过 `executescript()` 隐式提交破坏该事务。旧主键、source IDs、指纹、原始值保持；旧 `load_basis='unknown'`，catalog_id/availability/条件仍缺失，不按名称自动映射。

升级前关闭写入进程，先创建一致 SQLite 备份，避免只复制主库遗漏 WAL：

```python
from healthzip.db.repository import Repository
from healthzip.training.backup import backup_database, restore_database
repo = Repository('.local/healthzip.sqlite3')
backup_database(repo, '.local/backups/before-change.sqlite3')
repo.close()
# 恢复总写入新文件，不覆盖可能在运行的数据库。
restore_database('.local/backups/before-change.sqlite3', '.local/restored.sqlite3')
```

若要在第一次新版 Repository 打开之前备份旧库，用 Python 标准库连接旧文件并调用 `sqlite3.Connection.backup()`，再启动新版；不能先升级才把备份称为“升级前”。恢复后通过 `--db-path .local/restored.sqlite3` 检查，再人工决定切换。备份、恢复文件和导出 session 都属于私有健康数据，不提交 Git。

## 验证

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/training tests/integration/test_v13_training_ui.py --junitxml=artifacts/verification/training-tests.xml
ruff check src/healthzip/training src/healthzip/ui/training_page.py tests/training tests/integration/test_v13_training_ui.py
```

测试使用合成数据覆盖真实 Repository 落盘/重启、46 项目录、双侧片重 +5 kg、计划与事实、同日两场、相同真实组与请求重试、版本冲突、删除撤销、修改后建议失效、截止时间/补录/未来值/修订泄漏、等长/助力语义、休息计时和迁移回滚。此验证只证明软件契约，不证明训练建议对真人有效。

真实 Streamlit AppTest 完成两场胸部计划流程、缺依据候选冻结、反馈与周报，另覆盖目标/条件维护、替换/排序、非法数值、空历史导入导出和旧记录修订。请用项目 `.venv` 的 Streamlit 版本运行，不使用旧版系统 Streamlit 的 AppTest 代替。

## 独立离线记录页面

启动既有接收器后，打开 `http://127.0.0.1:8765/training/offline`；手机使用电脑局域网 IP。首次填接收器地址/token，点击“连接并缓存目录”。“下载独立离线页面”或 `/training/offline?download=1` 得到无外部脚本依赖的 HTML。

将下载文件在实际要记录的浏览器中打开，连接一次以缓存私有模板、器械和最近训练。随后断网或关闭电脑接收器也可以记录：每次输入先保存浏览器本地草稿，操作事件保存在 outbox；刷新本地文件后恢复。恢复连接点击“同步待发送记录”，按原 event_id 重试；两个相同的真实组具有不同 set UUID。发生同组并发修订时停止依赖事件并展示双方值，用户决定保留当前或采用更改。

公开动作种子随页面提供，因此没有缓存时也能临时训练、创建自定义动作；未知器械/条件仍按 unknown 保存。缓存模板开始时冻结明确的 template_version；后续服务器上的模板更新不会改变离线会话的原计划。用户可导出本机私有记录备份，恢复需明确确认，备份不含 token。

浏览器存储限于此设备及文件/网站来源，换浏览器不会自动共享。隐私模式、清理站点数据或系统回收可能清除缓存，请使用备份。手机系统是否允许直接打开本地 HTML 取决于浏览器；普通 HTTP 局域网页面在服务不可达时重新加载没有 service worker 保证，不能将这点说成原生离线 App。用户仍可在已打开页面继续保存本地草稿，再连回原接收器；完整的断网刷新验收使用下载的独立 HTML。

接收器新增端点：

- `GET /training/offline`：静态独立页面，无个人数据或 token。
- `GET /v1/training/bootstrap`：token 保护，缓存当前用户动作/模板/器械/最近30场训练。
- `GET /v1/training/catalog`、`GET /v1/training/sessions`：按需读取。
- `POST /v1/training/events`：`{device_id, events:[{event_id,operation,arguments}]}`，固定操作白名单、参数/所有权校验。每批最多100事件，冲突/失败后保留后续依赖事件。支持下载文件的 `Origin: null` 和同接收器来源，不向任意网站开放 CORS。

这些端点只操作本地 SQLite，不接模型 API 或公共知识库。

浏览器验收使用可选的 Playwright 和 Chromium，不增加运行时依赖：

```bash
PYTHONPATH=src python tests/training/offline_browser_check.py > artifacts/verification/offline_browser.json
```

该脚本在 390×844 视口中实际完成连接缓存 → 断网 → 模板开始 → 参考组预声明 → 记录并复制相同真实组 → 本地文件刷新恢复 → 丢失服务器回复 → 重试同步。校验两组只落盘一次、模板原计划槽仍只有一组，且没有 JavaScript 错误。`artifacts/verification/offline_browser.json` 为实际运行结果；浏览器缓存清理、系统文件打开限制和普通 HTTP 页面断网重载的边界仍如上所述。
