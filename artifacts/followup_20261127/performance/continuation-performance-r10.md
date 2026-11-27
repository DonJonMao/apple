# r10 性能与完整性实测汇总

运行器完成 12/12 项；全部进程成功：True。失败后的未运行项明确留空，已有失败和历史结果保留。
冻结源码、逐文件哈希、命令、原始样本、预算及完整性核对见 [JSON](continuation-performance-r10.json)。原压力夹具保持，统一截止 `2026-11-21T16:00:00+00:00`。
全量回归：发现 2576，执行 2576，通过 2576；失败／错误／跳过分别为 0／0／0。

热值均列原始样本数并重新核算 nearest-rank P95；冷值是单次。服务就绪单列，不混入点击耗时。报告冷生成包含本地分析、知识核查和冻结，审计导出与离线还原另计。

| 档位 | 后端冷生成 / 热 P95（s） | 浏览器冷生成 / 热 P95（s） | 浏览器冷重开 / 热 P95（s） | 正文 / 阅读载荷（B） |
|---|---:|---:|---:|---:|
| 两年个人 | 10.565 / 0.0212 | 11.972 / 1.446 | 1.111 / 0.489 | 21,360 / 352,921 |
| 10 万压力 | 122.122 / 0.0209 | 127.027 / 1.485 | 1.065 / 0.441 | 27,605 / 415,380 |
| 100 万压力 | 160.741 / 0.0237 | 165.981 / 1.519 | 1.102 / 0.633 | 28,549 / 511,709 |

| 档位 | 后端冷读 / 热 P95（s） | 历史菜单准备首次 / 热 P95（s） | 菜单热样本 / 全部首试成功 |
|---|---:|---:|---:|
| 两年个人 | 0.0058 / 0.0031 | 0.478 / 0.977 | 30 / True |
| 10 万压力 | 0.0065 / 0.0034 | 0.487 / 0.982 | 30 / True |
| 100 万压力 | 0.0077 / 0.0041 | 0.509 / 0.972 | 30 / True |

历史菜单准备包括就绪、真实输入和选项选择，与点击“打开”后的计时分开；未测完整导航总时钟，不能将 Open 延迟当作整个导航时间。

详情冷预算按事实＋趋势，复盘预览冷预算按首批事实；两者热预算均按事实＋趋势。

| 档位 / 页面 | 新进程周：首事实 / 趋势（s） | 运行冷周：首事实 / 趋势（s） | 运行冷月：首事实 / 趋势（s） | 热趋势 P95（s / n） |
|---|---:|---:|---:|---:|
| 两年个人 / 详情 | 3.783 / 3.802 | 3.058 / 3.077 | 3.169 / 3.194 | 0.746 / 30 |
| 两年个人 / 复盘预览 | 1.062 / 2.455 | 0.298 / 1.672 | 0.536 / 1.961 | 0.283 / 30 |
| 10 万压力 / 详情 | 4.143 / 4.177 | 3.337 / 3.361 | 3.421 / 3.424 | 0.787 / 30 |
| 10 万压力 / 复盘预览 | 5.281 / 6.667 | 4.800 / 6.193 | 4.642 / 6.097 | 0.214 / 30 |
| 100 万压力 / 详情 | 4.666 / 4.684 | 3.929 / 3.954 | 5.143 / 5.170 | 0.984 / 30 |
| 100 万压力 / 复盘预览 | 5.584 / 7.019 | 5.116 / 6.531 | 5.772 / 7.200 | 0.352 / 30 |

| 档位 | 审计导出（s / B） | 报告还原（s） | 工作流还原（s / 个） | 原始表哈希相同 / 两种还原准确 |
|---|---:|---:|---:|---|
| 两年个人 | 0.222 / 4,609,517 | 0.115 | 0.176 / 3 | True / True、True |
| 10 万压力 | 12.836 / 267,888,960 | 8.321 | 14.391 / 5 | True / True、True |
| 100 万压力 | 13.880 / 298,643,895 | 11.194 | 20.299 / 5 | True / True、True |

| 档位 | 后端生成 / 读取 / 审计峰值树 RSS（KiB） | 报告浏览器峰值（KiB） | 详情 / 预览峰值（KiB） |
|---|---:|---:|---:|
| 两年个人 | 436,352 / 40,240 / 97,504 | 1,264,280 | 1,327,156 / 1,023,996 |
| 10 万压力 | 2,092,664 / 40,808 / 2,182,172 | 3,151,364 | 1,351,396 / 1,790,832 |
| 100 万压力 | 2,499,868 / 42,224 / 2,472,600 | 3,593,132 | 1,525,508 / 1,823,500 |

峰值树 RSS 采用周期采样，短峰可能遗漏。浏览器／页面列包含该任务的隔离 Streamlit 与 Chromium，按整个任务汇总；后端列取各阶段自身回执，不与外层监控重复计数。CPU 与宿主负载原样保留在资源样本中。

预算未达：

- `personal.page.detail.budgets.running_week_le_3s`
- `personal.page.detail.budgets.running_month_le_3s`
- `100k.backend.generation.budgets.cold_le_15s`
- `100k.browser_report.generation.budgets.cold_interactive_within_budget`
- `100k.page.detail.budgets.running_week_le_3s`
- `100k.page.detail.budgets.running_month_le_3s`
- `100k.page.preview.budgets.running_week_le_3s`
- `100k.page.preview.budgets.running_month_le_3s`
- `1m.backend.generation.budgets.cold_le_15s`
- `1m.browser_report.generation.budgets.cold_interactive_within_budget`
- `1m.page.detail.budgets.running_week_le_3s`
- `1m.page.detail.budgets.running_month_le_3s`
- `1m.page.preview.budgets.running_week_le_3s`
- `1m.page.preview.budgets.running_month_le_3s`

验证失败／未完成：

- artifacts/followup_20261127/performance/continuation-browser-report-personal-r10/measured-source-manifest.json: source identity mismatch
- artifacts/followup_20261127/performance/continuation-browser-report-100k-r10/measured-source-manifest.json: source identity mismatch
- artifacts/followup_20261127/performance/continuation-browser-report-1m-r10/measured-source-manifest.json: source identity mismatch

验证边界：

- 共享 aarch64 主机有 192 个逻辑 CPU、约 2 TiB RAM；其他宿主负载不受控，不能替代普通设备性能实测。
- 本任务重测量顺序执行，OS 缓存未清；新进程、服务就绪、运行中新范围、热返回分开计时。
- 真实 Chromium 交互验证使用新渲染身份、实际数值和图点；实体 iPhone、Safari 与软键盘尚未验证。
- 隔离测量未配置目标远程模型；远程模型质量、独立专家审定与人体效度未由这些软件测量证明。
- 完整审计文件仅保留在合成临时工作区；本汇总只读取计量元数据，不打开或复制完整审计包。
- 原有失败、历史性能和原始样本全部保留；本汇总不覆盖历史证据。
