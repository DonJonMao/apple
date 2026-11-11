# v1.4 动作目录与历史定义验收

本轮基线为 `912aefc`。当前目录来源是 **2026-11-11 实际读取的 wger API v2 完整快照**，不是按预期数量生成的夹具。快照身份为 `wger.e9327e0394fd185d41d4b7f929e166a90730521f78b3c06207883d0a3f302414`。九类 API 共 60 页，966 个唯一动作、3959 条翻译、389 张图片、78 个视频；图片覆盖 282 个动作，视频覆盖 46 个动作。分页请求、接收时间、原始字节 SHA256 和链接见 [manifest](../artifacts/v14/catalog/manifest.json)。数量随下一次实际完整同步变化，不是代码配额。

旧 46 个 `psa.ex.*` ID 和定义全部保留。逐项映射见 [46 项清单](../artifacts/v14/catalog/legacy-46-mapping.json)：8 项根据真实原文与器械信息确认目录实体相同，以旧 ID 展示；其余保留独立身份或待核对，绝不凭中文名强合并。当前共展示 1004 个公共实体。这里的确认是 AI 辅助动作身份映射，**不是人工专业审阅或生理关系批准**。

原始上游中文翻译为 86 条。8 项沿用原项目中文名后，当前 wger 展示投影为 85 个上游译名、8 个旧目录名称、873 个项目 AI 译稿；译稿保留英文原名和来源身份，未宣称已完成人工术语核对。说明正文仍保留上游实际语言。少数含糊的上游命名在译稿中明确标为待核对。完整中文状态及源 UUID 见 [中文名称工件](../artifacts/v14/catalog/chinese-names.json)。

## 实际入口与边界

`TrainingService.search_exercises` 保持旧列表接口；`search_catalog(query, offset, limit, **filters)` 返回 `items/total/snapshot_id`。中文、公开/私人别名、英文和稳定 ID 都可查找，精确命中优先。主界面提供中文器械/部位/模式筛选、分页、动作步骤、图片选择、视频控件、逐项许可与署名。每页最多 50 项，单个可选表格逐项显示中文名称、器械、部位和本地缩略图；点击条目仍选中原动作 ID。页面只读取已下载的本地文件，不在打开动作详情时连接 wger。

上游设备数组完整保存。支撑设施不被当作阻力器械；不明确的类别为待确认。新来源记录模式没有统一设成次数：尚未核对的动作可以浏览，用户在记录前明确选择次数/时长/距离、实际器械和负荷口径，保存带 `derived_from` 的私人记录定义。原有次数、平板支撑时长、农夫行走距离入口继续使用既有定义。社区肌群标签只用于导航，`reviewed_anatomy` 保持空，不产生刺激权重、有效组数系数或恢复百分比。

目录的 `definition_version` 与 `presentation_version` 分开。翻译、别名、描述、图片不改变测量定义或条件键；上游设备/变式语义变化增加定义版本。会话和模板冻结定义快照与指定版本，历史读取不再动态用当前名称覆盖当时名称。上游删除只停用新搜索入口；UUID 更换进入映射队列。媒体许可变化或撤回会停用当前本地展示，即使原 blob 仍留在审计缓存。

## F05、F06

F05 原基线中，建立第二场后选择器仍停留第一场。现只以 `resume_training` 作为页面会话指针；创建成功立即选中新场，旧场由用户明确恢复。真实 AppTest 分别添加动作与实际组，检查组所属会话，不只比较 session state。

F06 原基线中，次数 v1 更改为时长 v2 后，历史另存模板意外使用 v2 并携带旧次数目标。现模板显式冻结 `definition_version` 和 `exercise_snapshot`；历史复制默认保留当时定义，跨记录模式目标被拒绝，公开新目录不升级旧模板。测试分别覆盖次数→时长、负荷口径变化、名字更新、时长历史 JSON 导出/导入、离线旧模板开始。

这三项原基线反例均真实失败，见 [baseline-pytest.xml](../artifacts/v14/catalog/baseline-pytest.xml)。修复后的训练、交换、离线和真实 Streamlit 75 项回归结果见 [fixed-pytest.xml](../artifacts/v14/catalog/fixed-pytest.xml)。最终目录 18 项单点验收见 [catalog-final-pytest.xml](../artifacts/v14/catalog/catalog-final-pytest.xml)。完整 1004 个公共显示名称已检查不存在内部翻译标记残留，见 [中文显示验收](../artifacts/v14/catalog/chinese-display-validation.json)；这项检查只证明显示完整性，不替代译文语义审核。

## 媒体、离线包和运行命令

每个媒体对象单独核对 Creative Commons 许可 URL、作者、原作链接和作用域，代码许可证不授予媒体使用权。未知许可不下载；原图经过解码验证，视频检查实际 ISO BMFF/QuickTime 容器块完整性；损坏文件标记 failed。每份文件以内容 SHA256 保存，重复运行校验并复用缓存。当前实际状态、字节数和失败原因以 [coverage](../artifacts/v14/catalog/coverage.json) 与 [逐项媒体清单](../artifacts/v14/catalog/media-manifest.json) 为准，不能把计划下载数量当已下载数量。源视频合计约 3.57 GB。

**2026-11-11 13:44:57 UTC 冻结交付快照：389/389 图片已缓存（覆盖282动作），61/78 视频 ready（覆盖35动作），17视频 pending。** 后台下载继续运行，后续成功回执不改变本包冻结分母。78个视频的实际 HEAD `Content-Length` 合计3,570,623,823 bytes，与API size逐项一致；见 [HEAD核验](../artifacts/v14/catalog/video-head-verification.json)。尚无成功回执的片段不计ready。正式离线包包含450个媒体对象、417个去重文件，1,712,936,494 bytes；纯文本包805,024 bytes。两包均含1004个公共动作，全部ZIP CRC、媒体引用路径和每个包内媒体SHA256检查通过；精确hash与分母见 [离线包验收](../artifacts/v14/catalog/offline-package.json)。默认安装、覆盖清单、逐项媒体清单与离线包均使用同一冻结公共快照，计数一致性见 [本轮交付刷新](../artifacts/v14/catalog/media-delivery-refresh.json)。

61 个 ready 视频中，40 个来自此前缺少成功回执的本地完整 blob。恢复逐项验证唯一来源文件大小、本地全文件 SHA256 与完整容器，并在同一强 ETag 下比较来源首/中/尾各 64KiB 与完整 `moov`。**来源没有提供可核验的全文件 checksum；ETag 是不透明验证标记，所比较区间之外的远端字节未逐字节核对。** 不能把本地完整 hash 与范围一致冒充远端全文件 checksum 证明。40 项精确范围、来源身份、时间和限制见 [恢复回执](../artifacts/v14/catalog/cache-recovery.json)，媒体清单对应项也保留这一限制。

视频保持来源原始编码，没有把转码说成原始字节。上游 54 个视频为 HEVC，24 个为 H.264；HEVC 需要支持该编码的浏览器或播放器。本次真实浏览器播放验收使用 `wger.video.21` 的 H.264 文件，已缓存后断网播放，实际解码为 640×352、时长约 15.93 秒。

正式 ZIP 另经全新 Chromium 上下文直接验收：完整解压，导航前断网，从包内 `file:` 路径读取图片与 H.264 视频，未使用 IndexedDB 媒体副本，HTTP 请求为 0；1004 项目录、6000×2188 图片与实际视频播放通过。包 hash、解码尺寸、播放进度和边界见 [离线包浏览器回执](../artifacts/v14/catalog/offline-package-browser.json)。这项验收不证明 HEVC 兼容性。

```bash
# 只有显式 fetch/media 命令联网；页面和服务初始化不联网。
.venv/bin/python -m healthzip.training.catalog_cli fetch
.venv/bin/python -m healthzip.training.catalog_cli validate --snapshot <完整快照目录>
.venv/bin/python -m healthzip.training.catalog_cli diff --previous <旧快照> --snapshot <新快照>
.venv/bin/python -m healthzip.training.catalog_cli publish --db .local/healthzip.sqlite3 --snapshot <完整快照目录>
.venv/bin/python -m healthzip.training.catalog_cli media --db .local/healthzip.sqlite3
.venv/bin/python -m healthzip.training.catalog_cli coverage --db .local/healthzip.sqlite3

# ZIP 内为 index.html、catalog.json、media-attribution.json 及真实 media/<hash> 文件。
.venv/bin/python -m healthzip.training.catalog_cli offline --db .local/healthzip.sqlite3 --output .local/catalog/HealthZIP-catalog-offline.zip
.venv/bin/python -m healthzip.training.catalog_cli offline --db .local/healthzip.sqlite3 --output .local/catalog/HealthZIP-catalog-text-only.zip --text-only
```

离线包存于本地 `.local/catalog/`，不提交 Git。解压整个目录后打开 `index.html`，不能只抽取 HTML 后声称媒体仍随包存在。纯文本包是独立选项，完整动作仍可检索和记录。浏览器连接本机 REST 后可以缓存单个动作或所有已下载媒体；媒体字节在 IndexedDB，目录详情也单独缓存，localStorage 仅保存精简检索投影和训练草稿，不塞视频 base64。新离线导出使用已安装公共目录；私人动作、别名、收藏和训练资料不进入公开包。

真实 Chromium 验收已加载 1004 个公共动作，在断网重启后保留完整目录、读取 IndexedDB 中的示范图片并播放已缓存 H.264 视频，同时以旧模板的 v1 时长定义记录 30 秒。结果见 [offline-browser.json](../artifacts/v14/catalog/offline-browser.json)，截图见 [离线目录](../artifacts/v14/catalog/offline-catalog.png)。截图仅使用合成训练；其中动作图为 wger 用户 `utkb` 的 CC BY-SA 4.0 图像，对应 `wger.image.346` 等记录，原作 URL、许可与 hash 见媒体清单。截图中的中文字体只为验收环境本地加载，产品不依赖外部字体服务。

## 迁移、恢复与私人记录

Repository 统一执行 schema v4 事务；目录模块没有独立的全局版本号，也不自行提交迁移。新增公共目录表和历史定义快照列采用增量迁移，源事实、旧 ID、数值与单位不重算。只有所有分页、唯一 ID、外键和页哈希通过的快照才能在事务内发布；失败快照保持失败，不把缺页当删除。

首次默认数据库安装前已用 SQLite backup API 备份已提交 WAL 到 `.local/backups/v14-before-catalog-*.sqlite3`；当时逐表比较 34 张原始私人表的原始列元组、数量和 SHA256，结果一致。这是历史安装证据。本轮媒体更新再次通过 SQLite backup API 新建 `.local/backups/v14-before-media-cache-*.sqlite3`，直接 SQLite 连接设置授权器，仅允许公共目录/schema 表读取及 `catalog_media`、`schema_meta` 写入，拒绝私人 SQL 读取/写入及 DDL；本次没有读取或重新哈希私人记录。五张公共身份、定义、翻译和快照表更新前后 hash 不变。公开 [安装验收](../artifacts/v14/catalog/default-install.json) 保留历史结果并追加本次 `media_cache_update`，不含私人值或机器绝对路径。恢复时关闭应用，将备份恢复到**新数据库路径**，核对后再在侧栏切换；不要覆盖正在运行的库。

## CAT-01 至 CAT-18 对照

|验收|实现与实际证据|边界|
|---|---|---|
|CAT-01|60 页完整 manifest；966 唯一动作与独立翻译/媒体分母；JSON Schema 校验全部来源实体。|后续按真实快照，不硬编码配额。|
|CAT-02|中断、重复页、篡改页与重复发布测试；旧已发布目录持续可读。|失败页不生成删除事实。|
|CAT-03|旧 46、私人别名/收藏、合成历史条件键与 30 单边片重原值保持测试；默认库原列哈希核对。|不根据名字重解释负荷。|
|CAT-04|46 项逐项原文定位/器械/模式/口径/结论工件。|只有 8 项确认实体关系，其余不合并。|
|CAT-05|来源 UUID 与既有 ID 独立；上斜/平板、史密斯/杠铃、助力/负重保持不同身份。|variation_group 仅为来源关联。|
|CAT-06|展示更新版本与历史冻结测试；改名不改变条件键或旧定义。|历史照片可以因当前许可停用。|
|CAT-07|源设备语义变化产生定义 v2；旧 v1 可读；F06 模式/口径与离线模板回归。|采用新定义需用户明确操作。|
|CAT-08|删除停用、UUID 更换映射队列、许可撤回停用本地媒体测试。|保留原事实，不级联删历史。|
|CAT-09|中文/别名/英文/稳定 ID、排序与分页测试；完整中文状态工件。|译稿不是人工术语审定。|
|CAT-10|389 图/282 动作、78 视频/46 动作分别报告；真实本地媒体文件及浏览器打开。|下载完成状态按媒体清单逐项统计。|
|CAT-11|无图、合成损坏文件、无许可分别验收。|不用邻近变式图片补位。|
|CAT-12|逐项作者、许可、原作、hash、文件验证；离线包携带署名清单。|不从 AGPL 推导图片许可。|
|CAT-13|真实 Chromium 完整目录断网重启、IndexedDB 图片、旧定义模板；旧丢响应重试回归继续通过。|连接本机同步身份，不按名称重匹配。|
|CAT-14|既有训练负荷语义/助力方向/单边片重/每只哑铃回归保留。|未知杆重、机械倍率、体重不补造。|
|CAT-15|次数、时长、距离目标控件与校验；时长历史模板/交换/离线回归。|新上游未核对模式要求用户确认。|
|CAT-16|完整私人自定义字段、来源变式、公开白名单导出；私人别名不进目录包。|公共同步不覆盖私人定义。|
|CAT-17|来源标签和 `reviewed_anatomy` 分开；导航状态测试。|教材关系批准数 0，无权重推断。|
|CAT-18|Repository 事务迁移回归与目录重复发布；旧交换文件回归保留；源身份不足标为未验证。|备份本地保存，不公开私人数据库。|

核心新增测试为 `tests/training/test_v14_catalog.py`，联网读取与真实浏览器为显式命令，不把公网成功替代离线软件回归。`tools/v14_catalog_evidence.py` 仅导出公共来源/许可字段；`tools/v14_catalog_browser.py` 先拒绝含私人训练的目录数据库，再创建临时合成训练验收。

## 后台媒体完成后的本地更新

后台下载写入独立公共目录库，每完成一个文件就提交成功回执；队列按来源体积从小到大调度。已验收完整文件直接复用，未完成文件保留 URL、来源验证标记和总长度。续传要求精确 Range、同一 ETag/Last-Modified 及总长度，响应不符时拒绝拼接。4 份既有片段共 40,370,176 bytes 已重新核对末尾 64KiB 与同一强 ETag，见 [片段核验](../artifacts/v14/catalog/partial-resume-verification.json)，不计入 ready。

本轮13:44:57 UTC快照的默认健康库安装已挂载389图和61视频。后续复用新完成文件时运行专用工具；它先备份默认库，再通过 SQL 授权器限制访问范围：

```bash
PYTHONPATH=src .venv/bin/python tools/v14_download_catalog_media.py --workers 4
PYTHONPATH=src .venv/bin/python tools/v14_install_media_cache.py
PYTHONPATH=src .venv/bin/python tools/v14_package_catalog_media.py
PYTHONPATH=src .venv/bin/python tools/v14_catalog_evidence.py --snapshot <完整快照目录>
PYTHONPATH=src .venv/bin/python tools/v14_package_browser.py
```

下载工具使用文件锁阻止重复进程，逐文件成功后写日志；锁文件与 PID 记录本身不证明进程仍在运行，须用操作系统进程状态核实。

冻结前的13:42:37 UTC实时观察见 [媒体进度历史回执](../artifacts/v14/catalog/media-live-progress.json)：当时已ready的389图和61视频随后在13:44:57 UTC进入本次新冻结包。下载进程经操作系统核实持续运行，未重启；17个pending视频的来源完整文件大小合计2,040,624,226 bytes，片段不计ready。新包再次通过全新Chromium上下文的断网file路径加载和实际H.264播放，HTTP请求为0。后续live缓存可继续增长；交付计数以本次冻结包、默认安装与对应浏览器回执为准。离线包工具先冻结公共 SQLite 快照，再验证全部 ZIP CRC、媒体路径和每个包内媒体 SHA256，通过后替换正式包。本次提交的覆盖工件是带时间的冻结交付快照；后续新增 ready 以本地成功回执为准，不能把 pending 或片段计为可用。

本轮目录/续传及安装授权器共 24 项测试通过，见 [媒体回归](../artifacts/v14/catalog/media-cache-final-pytest.xml)。合成反例覆盖来源标记变化、范围/总长度不符时保留原片段、私人 SQL 读写拒绝和 WAL 备份；真实浏览器播放另见前述回执。

## 列表与媒体状态补充验收

真实 AppTest 使用 51 个合成来源动作验证每页 50 项、逐项器械/部位/本地缩略图和点击后的稳定 ID；末页仅 1 项。主页面与离线页面共用媒体状态词表，分别显示无动作示范、尚未下载、下载失败、许可不明和来源撤回。目录 19 项回归全部通过，见 [补充 pytest](../artifacts/v14/catalog/catalog-ui-followup-pytest.xml)。真实 Chromium 已重新验证上述中文状态、1004 项目录断网恢复、旧模板定义和 H.264 本地播放，见 [浏览器回执](../artifacts/v14/catalog/offline-browser.json)。两份本地离线 ZIP 已随页面更新重建并重新检查全部成员 CRC 与媒体引用；该更新不改变媒体获取覆盖分母。

## STR-05/06 历史肌肉关系版本

`TrainingService.add_exercise(..., reviewed_anatomy_snapshot=...)` 提供显式采用入口：调用者提交映射身份/版本、适用动作ID/定义版本、直接与间接肌肉列表、批准状态、审核者、审核时间和非空来源定位引用。服务核对格式、作用域、时区及时间顺序，将其冻结在当次 `condition_json.reviewed_anatomy_snapshot` 中，独立于物理 `condition_key`。这个入口保存可审计的调用者审核记录，不认证审核者身份，也不代替阅读来源、核对专业结论；本轮没有创建任何生产批准映射。

分析只消费逐组冻结快照；旧记录缺快照保持未知，不能由当前 `context.muscle_mappings` 追溯补齐。同一映射身份/版本不得改写内容，新的明确采用使用新版本；直接/间接分组保留版本、来源和逐组冻结hash。不允许通过数值编辑或导入来源修订换掉旧组的审核快照。模板与离线重试采用既有版本，JSON交换保留原冻结时间并核对其不晚于原组可见时间；缺少原时间时拒绝把该映射当成历史已知。

真实服务→持久化→历史截止时间/当前分析→模板→离线事件重试→JSON交换的测试为 `tests/integration/test_v14_anatomy_history.py`。连同训练、交换、目录和真实 Streamlit 回归共 **94项通过**，见 [历史映射与兼容验收](../artifacts/v14/catalog/anatomy-history-pytest.xml)。测试批准记录全部是隔离的合成夹具；上游肌群标签及当前生产目录仍无获批教材关系。

模板本身是计划：已有历史映射保留原绑定时间；仅提供审核内容时，新的 `frozen_at` 在真实训练实例创建时产生，避免重试同一模板事件时请求内容变化。最终历史映射 **14项定点检查通过**，包括已有/尚未有冻结时间的模板创建事件重试，见 [最终历史映射验收](../artifacts/v14/catalog/anatomy-final-pytest.xml)。整仓最终集合以根交付 manifest 为准。

分页预览最终使用单个可选表格，每页最多50项、本地缩略图缩至96×72并限制缓存512项，避免每次逐组编辑时生成数百个独立卡片控件。原多动作真实UI用例在未提高3秒单次重绘预算的情况下完整通过；最终目录19项回归9.38秒通过，见 [最终目录UI验收](../artifacts/v14/catalog/catalog-ui-final-pytest.xml)。
