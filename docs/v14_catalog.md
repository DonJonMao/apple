# v1.4 动作目录与历史定义验收

本轮基线为 `912aefc`。当前目录来源是 **2026-11-11 实际读取的 wger API v2 完整快照**，不是按预期数量生成的夹具。快照身份为 `wger.e9327e0394fd185d41d4b7f929e166a90730521f78b3c06207883d0a3f302414`。九类 API 共 60 页，966 个唯一动作、3959 条翻译、389 张图片、78 个视频；图片覆盖 282 个动作，视频覆盖 46 个动作。分页请求、接收时间、原始字节 SHA256 和链接见 [manifest](../artifacts/v14/catalog/manifest.json)。数量随下一次实际完整同步变化，不是代码配额。

旧 46 个 `psa.ex.*` ID 和定义全部保留。逐项映射见 [46 项清单](../artifacts/v14/catalog/legacy-46-mapping.json)：8 项根据真实原文与器械信息确认目录实体相同，以旧 ID 展示；其余保留独立身份或待核对，绝不凭中文名强合并。当前共展示 1004 个公共实体。这里的确认是 AI 辅助动作身份映射，**不是人工专业审阅或生理关系批准**。

原始上游中文翻译为 86 条。8 项沿用原项目中文名后，当前 wger 展示投影为 85 个上游译名、8 个旧目录名称、873 个项目 AI 译稿；译稿保留英文原名和来源身份，未宣称已完成人工术语核对。说明正文仍保留上游实际语言。少数含糊的上游命名在译稿中明确标为待核对。完整中文状态及源 UUID 见 [中文名称工件](../artifacts/v14/catalog/chinese-names.json)。

## 实际入口与边界

`TrainingService.search_exercises` 保持旧列表接口；`search_catalog(query, offset, limit, **filters)` 返回 `items/total/snapshot_id`。中文、公开/私人别名、英文和稳定 ID 都可查找，精确命中优先。主界面提供中文器械/部位/模式筛选、分页、动作步骤、图片选择、视频控件、逐项许可与署名。页面只读取已下载的本地文件，不在打开动作详情时连接 wger。

上游设备数组完整保存。支撑设施不被当作阻力器械；不明确的类别为待确认。新来源记录模式没有统一设成次数：尚未核对的动作可以浏览，用户在记录前明确选择次数/时长/距离、实际器械和负荷口径，保存带 `derived_from` 的私人记录定义。原有次数、平板支撑时长、农夫行走距离入口继续使用既有定义。社区肌群标签只用于导航，`reviewed_anatomy` 保持空，不产生刺激权重、有效组数系数或恢复百分比。

目录的 `definition_version` 与 `presentation_version` 分开。翻译、别名、描述、图片不改变测量定义或条件键；上游设备/变式语义变化增加定义版本。会话和模板冻结定义快照与指定版本，历史读取不再动态用当前名称覆盖当时名称。上游删除只停用新搜索入口；UUID 更换进入映射队列。媒体许可变化或撤回会停用当前本地展示，即使原 blob 仍留在审计缓存。

## F05、F06

F05 原基线中，建立第二场后选择器仍停留第一场。现只以 `resume_training` 作为页面会话指针；创建成功立即选中新场，旧场由用户明确恢复。真实 AppTest 分别添加动作与实际组，检查组所属会话，不只比较 session state。

F06 原基线中，次数 v1 更改为时长 v2 后，历史另存模板意外使用 v2 并携带旧次数目标。现模板显式冻结 `definition_version` 和 `exercise_snapshot`；历史复制默认保留当时定义，跨记录模式目标被拒绝，公开新目录不升级旧模板。测试分别覆盖次数→时长、负荷口径变化、名字更新、时长历史 JSON 导出/导入、离线旧模板开始。

这三项原基线反例均真实失败，见 [baseline-pytest.xml](../artifacts/v14/catalog/baseline-pytest.xml)。修复后的训练、交换、离线和真实 Streamlit 75 项回归结果见 [fixed-pytest.xml](../artifacts/v14/catalog/fixed-pytest.xml)。最终目录 18 项单点验收见 [catalog-final-pytest.xml](../artifacts/v14/catalog/catalog-final-pytest.xml)。完整 1004 个公共显示名称已检查不存在内部翻译标记残留，见 [中文显示验收](../artifacts/v14/catalog/chinese-display-validation.json)；这项检查只证明显示完整性，不替代译文语义审核。

## 媒体、离线包和运行命令

每个媒体对象单独核对 Creative Commons 许可 URL、作者、原作链接和作用域，代码许可证不授予媒体使用权。未知许可不下载；原图经过解码验证，视频检查实际 ISO BMFF/QuickTime 容器块完整性；损坏文件标记 failed。每份文件以内容 SHA256 保存，重复运行校验并复用缓存。当前实际状态、字节数和失败原因以 [coverage](../artifacts/v14/catalog/coverage.json) 与 [逐项媒体清单](../artifacts/v14/catalog/media-manifest.json) 为准，不能把计划下载数量当已下载数量。源视频合计约 3.57 GB。

**本次交付快照的媒体状态：389/389 图片已缓存（覆盖 282 动作），4/78 视频已缓存（覆盖 3 动作），74 视频继续后台下载。** 78 个视频的实际 HEAD `Content-Length` 合计 3,570,623,823 bytes，与 API size 逐项一致；见 [HEAD 核验](../artifacts/v14/catalog/video-head-verification.json)。后台已写入但尚无成功回执的文件不算 ready。现有完整可用离线包包含所有已验收媒体：393 个媒体对象、360 个去重文件，315,109,495 bytes；纯文本包 794,573 bytes。两包均含 1004 个公共动作，ZIP 校验与所有包内媒体引用检查通过；hash 与精确分母见 [离线包验收](../artifacts/v14/catalog/offline-package.json)。

视频保持来源原始编码，没有把转码说成原始字节。上游 54 个视频为 HEVC，24 个为 H.264；HEVC 需要支持该编码的浏览器或播放器。本次真实浏览器播放验收使用 `wger.video.21` 的 H.264 文件，已缓存后断网播放，实际解码为 640×352、时长约 15.93 秒。

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

默认本地数据库安装前已用 SQLite backup API 备份已提交 WAL 到 `.local/backups/v14-before-catalog-*.sqlite3`。安装后逐表比较 34 张原始私人表的原始列元组、数量和 SHA256，结果一致。公开 [安装验收](../artifacts/v14/catalog/default-install.json) 只保存通过状态与分母，不含私人值或机器绝对路径。恢复时关闭应用，将备份恢复到**新数据库路径**，核对后再在侧栏切换；不要覆盖正在运行的库。

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

本轮后台下载写入独立公共目录库；默认健康库当前已挂载389图和4视频。下载完成后，可先复用已校验文件，不重复联网下载：

```bash
.venv/bin/python - <<'PY'
from healthzip.db.repository import Repository
from healthzip.training.catalog_media import reuse_media_cache
source = Repository('.local/catalog/catalog.sqlite3')
target = Repository('.local/healthzip.sqlite3')
try:
    print(reuse_media_cache(target, source))
finally:
    target.close()
    source.close()
PY
```

随后运行上方的离线包导出命令。新的ready数量应从当前回执重新统计；本次提交的覆盖工件是冻结交付快照，不把仍在下载的74个视频算作已经可用。
