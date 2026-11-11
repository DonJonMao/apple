# 动作库接入与图示改造：以 wger 为主库

适用代码基线：`912aefc`。本章是待实施设计，未修改源码。沿用现有 SQLite、TrainingService、Streamlit 和本地离线记录器，不迁入 wger 的整套训练管理应用。

## 1. 交付目标与已核实规模

将46个动作的种子目录扩展成可本地检索、中文显示、带来源和媒体信息的动作目录。wger 负责动作条目、器械/部位/肌群标签、描述、翻译、图片与视频的上游数据；权威教材/指南库负责专业解释和训练建议依据。动作条目被导入不意味着其全部肌群标签、技术说明已获专业认可。

2026-11-11官方API实测基线如下；后续同步以当次完整快照清单为准，不把这些数字写成永久常数：

| 对象 | 实测规模 | 正确解释 |
|---|---:|---|
| `exerciseinfo`动作 | 966 | 唯一动作，不是翻译数量 |
| 翻译 | 3959条，其中中文86条 | 不能宣称全量中文现成 |
| 图片 | 389张，覆盖282个动作 | 其余684个动作没有图片；不能把图片数当有图动作数 |
| 视频 | 78个，覆盖46个动作 | 不能承诺每个动作都有视频 |
| 图片许可 | CC BY-SA 3.0：88；CC BY-SA 4.0：295；CC0：6 | 每个媒体对象分别保留许可和作者 |
| 视频许可 | 78个均CC BY-SA 4.0 | 与软件代码的AGPL许可分别处理 |

官方读取入口：`https://wger.de/api/v2/exerciseinfo/`、`exerciseimage/`、`video/`、`exercise-translation/`、`language/`、`license/`。官方同步说明：https://wger.readthedocs.io/en/latest/administration/commands.html 。

## 2. 现有实现的接入位置

| 现有文件/方法 | 当前行为 | 要做的改动 |
|---|---|---|
| `training/service.py::_seed_catalog` | 每次服务初始化插入46项本地种子 | 保留为兼容和离线回退；网络同步移入显式目录命令，禁止页面初始化时联网 |
| `training/schema.py`、`db/repository.py::_migrate_schema` | 现有目录以`exercise_id + definition_version`为主键 | 原表与原ID保留，补来源、版本、翻译、媒体关系；所有迁移经Repository事务执行 |
| `training/service.py::get_exercise/search_exercises` | 单值器械类型、JSON内名称/别名，返回整个匹配列表 | 返回当前目录展示投影、可分页结果与总数；读取本地翻译/媒体，保留指定旧定义版本读取 |
| `training/semantics.py::condition_snapshot` | 条件键含动作ID/版本、器械、口径、侧别、ROM等 | 保留物理可比身份；改名、翻译、换图不得改变条件键 |
| `ui/training_page.py::_selector/_catalog` | 文字选择；部分器械值为英文；自定义表单缺部位/模式 | 增加中文分类、动作详情/媒体、许可说明和完整自定义字段 |
| `training/offline.py::recorder_html` | 直接读取46项种子 | 改为导出已安装公共目录快照；不得仍把新库仅接入主页面 |
| `training/offline.py::browser_bootstrap` | 私有训练数据与完整目录混合返回 | 返回明确catalog版本和可增量更新的目录；媒体走独立缓存，不把大文件塞进localStorage |
| `training/exchange.py` | 导出引用到的动作定义；导入未知定义作为custom | 增加可选来源/展示/媒体清单，保留兼容读取；不能把外部公共动作误标成用户原创 |
| `ui/offline_recorder.html`及现有REST模块 | 本地记录和事件重放 | 使用同一动作ID、目录版本与分页/检索契约；补本地媒体读取及缺图状态 |

代码目录建议只增加职责明确的`training/catalog_import.py`（抓取/校验/映射/发布）、`training/catalog_media.py`（媒体下载/验证/本地路径）及`training/catalog_cli.py`（或挂到现有CLI）。复用现有服务与迁移，不为导入额外引入图数据库或Agent框架。

## 3. 数据模型与版本规则

保留`exercise_catalog`作为训练服务的本地定义表。公共原文快照和媒体字节存于`.local/catalog/`；其元数据可在现有SQLite新增下表。目录导出只允许公共表/字段白名单，不能导出私人别名、收藏、器械实例或训练记录。

| 表/对象 | 最低字段和约束 |
|---|---|
| `catalog_snapshot` | `snapshot_id`、provider、API/schema版本、fetched_at、完整性状态、页数、上游count、实际唯一ID数、manifest_sha256、raw_root、license_manifest、previous_snapshot_id。状态`staged/complete/published/failed`；只有完整快照可发布 |
| `catalog_source_record` | provider、source_id、source_uuid、snapshot_id、raw_sha256、raw_path、source_updated_at、license_json、author_json。唯一键`provider + source_uuid + snapshot_id`；无UUID时记录受控回退键，不能由名称生成身份 |
| `catalog_source_mapping` | provider、source_uuid、local_exercise_id、relation、status、理由、证据定位、版本、创建/确认记录。relation区分`exact_identity/variant_of/related/possible_duplicate`；只有确认的exact_identity参与去重展示 |
| `catalog_localization` | local_exercise_id、locale、名称/别名/说明、origin、source_record_id、translation_version、review_status、内容哈希。来源区分upstream、项目译稿、术语核对、用户私人别名；名称不承担物理身份 |
| `catalog_media` | provider_media_id、source_uuid、media_type、原URL、local_blob_hash、MIME/大小/尺寸/时长、is_main、许可ID/URL/作者/原作链接、license_scope、attribution_text、fetch_status、last_verified_at、适用动作变式。未知许可的媒体不进入下载发布清单 |
| `catalog_presentation` | local_exercise_id、presentation_version、name/description/tag/media引用、源快照、当前展示指针。与`definition_version`独立，防止翻译和图片更新改变力量比较身份 |

已有`exercise_alias`继续只承载私人别名，不能因公共目录更新而覆盖。新增公开别名使用localization记录。已有`exercise_preference`继续引用稳定本地ID。

本轮schema版本号由Repository与其他修复迁移统一分配；不得在目录模块和训练模块各自维护不兼容的“v4”。升级前备份；失败事务回滚；重复升级幂等。

### 规范化动作对象示例

以下为结构示例，`snapshot`/hash字段是占位，不得作为采集凭证使用；示例source UUID来自已读取的wger壶铃摆动条目：

```json
{
  "exercise_id": "catalog.wger.1b020b3a-3732-4c7e-92fd-a0cec90ed69b",
  "definition_version": 1,
  "presentation_version": 1,
  "source": {
    "provider": "wger",
    "source_id": 9,
    "source_uuid": "1b020b3a-3732-4c7e-92fd-a0cec90ed69b",
    "snapshot_id": "<actual-published-snapshot>",
    "raw_sha256": "<actual-64-hex-sha256>"
  },
  "names": {
    "en": {"text": "2 Handed Kettlebell Swing", "origin": "upstream"},
    "zh-CN": {"text": "双手壶铃摆动", "origin": "project_translation", "review_status": "draft"}
  },
  "recording": {
    "mode": "repetitions",
    "mode_basis": "catalog_mapping_review",
    "equipment_type": "kettlebell",
    "default_load_basis": "unknown",
    "requires_load_basis_confirmation": true,
    "allowed_load_bases": ["single_implement_kg", "unknown"]
  },
  "variant": {"parent_id": null, "source_variation_group": "a30b1f92-7b73-477e-abb0-e91993c5fb05"},
  "upstream_muscle_tags": {"primary": [11, 8], "secondary": [10, 6], "use": "navigation"},
  "reviewed_anatomy": null,
  "media_ids": [],
  "media_availability": "none_in_source"
}
```

为规范化对象编写实际JSON Schema：稳定ID、正整数版本、来源定位、记录模式、许可字段为受控类型；允许未知值，但不允许缺失时自动补成已确认。`mode_basis=catalog_mapping_review`必须有对应映射工件；样例本身不构成已核对记录。字符串说明和上游HTML是内容，不是可执行指令；仅以清洗后的文本/受控标记显示。

## 4. 上游快照导入、发布与更新

1. 显式执行目录同步，分页读取各对象，保存每页URL、响应时间、状态、原始哈希和next链接。抓取不携带私人健康/训练数据。
2. 校验分页完成、唯一ID、外键、语言/许可映射以及必需字段；区分记录数与唯一动作数。中断时留在staged，不能将缺页误认成上游删除。
3. 生成差异清单：新增、展示更新、定义变化、可能重复、上游删除、许可变化、媒体失效。用户正常训练继续使用上一个完整已发布快照。
4. 先在staging建立规范化目录与旧46映射，再在一个事务内发布当前指针。重复导入同hash不生成重复动作或多份媒体。
5. 更新中文说明或图片仅生成presentation版本；真实改变记录模式、物理变式/器械语义时生成新的definition版本。已有会话、模板版本和已冻结建议不自动升级。
6. 上游删除用tombstone，不物理删除本地历史依赖。默认新动作搜索隐藏已撤回条目；历史照常显示当时定义，并注明已停用。上游ID复用/UUID更换进入人工映射队列，不能凭名称续接旧身份。
7. 媒体许可撤回或范围变化时停止当前展示/下载并保留审计凭证；训练历史仍保留动作/数值，图片可显示“来源图片已不可用”。历史完整性不等于必须继续公开展示已停用媒体。

CLI交付接口可为：`catalog fetch --provider wger`、`catalog validate <snapshot>`、`catalog diff <old> <new>`、`catalog publish <snapshot>`、`catalog media fetch --snapshot <id>`、`catalog coverage --snapshot <id>`。实现时挂入现有命令体系，以上为接口目标而非声称现有命令已存在。

## 5. 旧46项、自定义动作与变式映射

旧`psa.ex.*` ID以及所有已保存`definition_version`必须原样保留。对46项逐项建立映射表，记录原ID、原英文/中文名称、候选wger UUID、器械、动作角度/路径、单双侧、记录模式、映射结论和理由。匹配到明确同一动作时，为旧本地ID添加wger来源关系和媒体，后续新记录仍使用该旧本地ID。未明确匹配的保留原条目，与wger新条目并存。

映射类型不能偷换：平板与上斜、杠铃与史密斯、普通与辅助/负重引体、双侧与单侧、腿屈伸与腿弯举不能因名字或肌群相近而合并。wger的variation_group只表示来源关联，不直接授予趋势可比性。其他中文库只能提供候选译名/别名，须核对动作身份及对应许可，不能以同一中文名覆盖wger或旧46身份。

对普通名称修正，展示名可更新，但冻结的训练会话、组记录、建议需要保留当时名称/定义快照；现有`get_session_exercise`会动态取目录定义，实施时应避免新展示文案重写历史事件视图。

自定义动作继续为私人条目；表单补齐部位、多选动作模式、器械类型、单双侧/变式说明、记录模式和口径选择。允许从公共动作复制为个人变式，保留`derived_from`，不给新变式继承“已审核专业关系”。用户自行命名或未找到动作不应阻止记录。公共同步不能修改私人名称、别名、收藏或自定义定义。

## 6. 负荷与记录语义不交给上游猜测

wger的equipment列表是导航信息，可能同时包含训练凳和阻力器械；不能简单取第一个设备作为负荷定义。保留原数组，并用受控映射区分支撑设施、阻力器械和替代器械。映射不明确则器械类别保持other/待确认；第一次实际记录让用户选定实际器械和口径，不能伪造已知条件。

| 情形 | 必须保留的记录行为 |
|---|---|
| 单边片重 | 保存原输入；只有用户确认两侧对称才能计算两侧片重；有效杆重未知时不补成20kg或某个史密斯常数 |
| 哑铃 | 每只重量、两只合计、单只使用分别记录；记录使用数量和次数是单侧、左右各自还是交替合计 |
| 助力器械 | 数字下降通常表示助力下降；保存机器/单位/设置，不默认换成“体重−助力”的有效负荷 |
| 插片/绳索 | 本台刻度就是本台刻度；无传动参数不换算为手端力，也不跨器械汇总趋势 |
| 自重/负重自重 | 区分体重、额外负重与无额外负重；不把全部体重自动当该动作阻力 |
| 等长/搬运 | 分别记录时长/距离及可选外部负重；不得统一成次数动作或套e1RM |

新库须维护`recording_mode`映射。由明确动作定义和人工核对的映射清单决定，不能默认966项均为次数。尚未核对的动作可浏览，实际记录时允许用户明确选择模式并形成私人记录定义。缺失影响分析的条件只阻止对应推断，不阻止保存原始记录。

## 7. 中文检索、媒体展示与离线

- 中文覆盖不能靠把86条中文翻译扩大表述为966条。对剩余条目建立完整译稿，采用统一肌群/器械/动作术语，保存英文原名、常用别名、来源与翻译状态；机器译稿与术语核对版明确区分。已知种子46项中文名可作为对应条目的优先显示名。
- 搜索同时支持中文名、别名、英文名和稳定ID；精确名称/别名优先，其次前缀/子串匹配，结果解释可读。无需为近千条目录先增加向量服务。增设分页和返回总数；筛选分类全部中文化。
- 列表给出动作名、器械、部位和小缩略图，详情提供大图、多张图片切换、视频控件、文字步骤、主要/次要肌群标签及可展开来源署名。视频默认不自动播放。
- 无图动作使用统一“暂无动作示范”占位，不把人体肌群图当成动作演示图，不把相似变式的图片借给当前动作。图片与具体动作/变式绑定；下载失败与上游本身无图分别显示。
- 媒体显式下载到内容哈希路径，记录原URL/MIME/尺寸/文件hash。断点重试幂等，损坏文件不进入ready状态。下载权限来自每项许可，不从API代码许可证推导。公开展示/导出携带对应署名、许可链接和必要的改动说明。
- 主程序从本地媒体服务读取；不在用户打开动作页时直接请求第三方图片。离线记录器导出目录manifest及已下载媒体包，本地浏览器使用IndexedDB/Cache Storage或包内资源，不能把全部视频base64写入localStorage。
- 保留轻量纯文本离线包选项；完整目录可检索，缺媒体仍可记录。与主页面同步时使用同一稳定动作ID和定义版本，不重新按名称猜测匹配。`recorder_html`必须停止只嵌入旧46种子，已下载内容在无网络、重启后仍可用。

## 8. 肌群标签与专业知识的接口

上游`muscles`、`muscles_secondary`按原义保留为来源标签，允许用于导航和标注“来源分类”。项目的教材核对关系单独存为`reviewed_anatomy`：动作/变式、肌肉、主要/协同/稳定作用、适用条件、教材ID/版次/章节/页码、核对记录及版本。

教材核对覆盖真正需要用于分析的关系；无需为每个常见肌肉功能等待一篇单独试验。来源标签不得自动变成“刺激占比”“有效组数系数”或某块肌肉恢复百分比。动作图片、社区步骤和教材指导冲突时，保留出处并处理该条冲突，不能用多数来源投票决定正确动作。

AI建议只能引用独立权威核心库中已核对的训练原则；动作库提供“用户做了什么动作、有哪些变式和器械”的实体上下文。图片丰富和动作数量大不构成建议可靠性的证明。

## 9. 验收清单

| 编号 | 验收输入/动作 | 必须满足的结果 |
|---|---|---|
| CAT-01 | 完整966动作基线快照 | 导入唯一动作数与manifest一致，翻译/媒体数分开报告，差异有原因；未来以真实新快照为准 |
| CAT-02 | 分页中断、重复页、重复同步 | 未完成快照不发布；重复导入不新增重复实体；旧目录持续可用 |
| CAT-03 | 已有46项和合成历史升级 | 原catalog ID、definition_version、负荷/次数、条件键与历史引用不变；收藏、模板和私人别名不丢 |
| CAT-04 | 46项逐项映射清单 | 每项有明确结论；未匹配不强合并；用户示例只占普通样例之一 |
| CAT-05 | 平板/上斜、杠铃/史密斯、辅助/负重引体 | 搜索可关联，但不得归并物理身份或混合力量趋势 |
| CAT-06 | 改中文名、说明、图片 | 只增加展示版本；不改变已有训练条件键，不重写历史冻结快照 |
| CAT-07 | 上游记录模式/器械语义变化 | 新定义版本只用于明确采用的新记录；旧会话/模板版本仍可读取 |
| CAT-08 | 上游删除、UUID变更、许可变化 | tombstone/待映射/媒体停用分别正确；无历史级联删除；缺页不视为删除 |
| CAT-09 | 中文/别名/英文检索 | 同一实体被正确找到；中文覆盖和译稿状态真实显示；翻译不能产生重复动作 |
| CAT-10 | 389图、78视频基线 | 媒体记录与实际覆盖282/46动作分别核对；图片/视频可本地打开；不伪造全覆盖 |
| CAT-11 | 无图、损坏下载、无许可字段 | 分别显示无示范/下载失败/暂不可用，不用错误变式图片补位 |
| CAT-12 | 媒体导出与署名 | 每项许可、作者、来源和hash可追溯；代码许可证不替代媒体许可 |
| CAT-13 | 主页面与离线页同动作记录 | 同一本地ID、定义版本和口径；断网/重启/事件重试不改动作身份，不退回只剩46项 |
| CAT-14 | 单边片重、每只哑铃、助力、器械刻度 | 全部维持原口径与正确方向；未知杆重/传动比/体重不补造 |
| CAT-15 | 平板支撑、搬运和普通次数动作 | 按时长/距离/次数分别记录，模板、历史、导入导出一致 |
| CAT-16 | 自定义动作/私人别名 | 本地持久化和重试正确；公共更新不覆盖；公共catalog导出不泄露私人资料 |
| CAT-17 | 社区肌群标签与教材关系 | 来源身份分别展示；无自动刺激权重、有效组数或恢复百分比 |
| CAT-18 | 迁移中断与恢复、旧交换文件 | 事务回滚、重跑幂等；旧文件仍可导入，来源信息不足保持未知 |

新增测试应落在`tests/training/test_catalog_import.py`、`test_catalog_mapping.py`、`test_catalog_media.py`及真实UI/离线集成测试。媒体测试使用自制合成图片/视频或许可明确的最小测试资产；核心回归不得依赖实时公网。另提供显式联网smoke命令核对真实API与媒体可用性，不能把联网成功代替软件回归或专业知识验收。

## 10. 交付物

交付目录适配代码、统一事务迁移、可重放manifest、旧46映射表、中文术语/别名表、逐项媒体许可与覆盖报告、可下载离线目录包、真实页面演示、迁移与恢复说明，以及CAT-01至CAT-18的实际证据。更新`DESIGN_SPEC.md`、`IMPLEMENTATION_STATUS.md`和需求追踪表，分别报告动作数、中文状态、图片/视频覆盖、专业标签核对状态，不能仅以“接入966条”宣布动作库全部完成。
