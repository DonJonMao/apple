# 训练闭环验收（2026-11-22）

本轮复用原 TrainingService、训练事件、稳定 UUID、修订冲突、离线草稿和训练组件。补充逐组可选停止原因及组类型、结束前明确保留或放弃草稿、动作进展与返回原训练入口。训练首页只读构建；实际命令仍经过原初始化和事务服务。没有要求先创建计划、模板或名称。

所有证据使用合成记录。浏览器是本机 Linux aarch64 上的 Chromium 158.0.8127.18；手机宽度模拟不等于真实 iPhone/Safari、软键盘或手机网络验收。

| 要求 | 实际验证与证据 | 状态 |
|---|---|---|
| U04 直接开始 | `A09_direct_start`；默认日期名称，直接进入记录 | 通过 |
| U05 单选添加/取消/重试 | 单击保存回同一训练、取消无写入；丢回执同 request ID 重试，无重复组 | 通过 |
| U06 小数与零 | 输入32.5×8、RIR=0；再次选动作与刷新后值不变；辅助重量0合法 | 通过 |
| U07 带入与完成事实 | 沿用为草稿，不复制实际RIR、停止原因、完成状态；未完成组不计完成 | 通过 |
| U08 恢复与冲突 | 延迟800ms真实回执、刷新未确认请求、断线重试、真实双页签冲突、显式重定基准；旧回执不覆盖新输入 | 通过 |
| U09 长训练滚动 | 30个动作，前10个各3组；文档主滚动，末端添加入口可达；取消选择返回原滚动位置 | 通过 |
| U10 六档宽度 | 320/375/390/430/768/1440；组件可用宽度扣除页面边距；主页面与训练行无横向溢出 | Chromium通过 |
| U11 焦点/加载/键盘 | 稳定DOM、局部回执不丢焦点；18px加载图标、输入字号与触控尺寸检查；视口高度压到430px仍能到末行 | 物理手机键盘未验证 |
| U12 初始空工作区 | 不写目录种子也可显示首页；他人持有写锁时仍可读取；实际开始后目录及筛选恢复可用，无示范完成量 | 软件通过 |
| U13 返回/结束/历史修订 | 返回首页不结束；结束前摘要及明确草稿处置；本机无效未同步值仍可恢复；结束后更正、删除、撤销与源组一致 | 通过 |
| D14 达目标停止 | 30kg/侧，首组10→10；RIR未知保持未知；没有自动停滞结论 | 通过 |
| D15 完整组序 | 后组10→8，休息180→90秒；实际进展页显示具体记录，并能打开原训练 | 通过 |

核心工件：

- [浏览器完整过程](../artifacts/master_redesign/training/training-browser-results.json)：真实 Streamlit 组件及服务回执；`geometry_*`保存每档实际几何量。
- [边界交互](../artifacts/master_redesign/training/training-edge-results.json)：时长/距离/自重/辅助语义、已保存顺序、删除撤销、工作区隔离和双页签。
- [搜索过程](../artifacts/master_redesign/training/training-search-results.json)：30次，包含防抖；与服务端结果一致、用户别名、收藏和筛选。
- [动作进展](../artifacts/master_redesign/training/exercise-progress.json)、[实际手机宽度截图](../artifacts/master_redesign/training/exercise-progress-mobile.png)。
- [修改前截图](../artifacts/master_redesign/training/before/)、[修改后截图](../artifacts/master_redesign/training/after/)、[录屏](../artifacts/master_redesign/training/video/)。

| 同机操作 | 样本数 | P50 | P95 | 口径 |
|---|---:|---:|---:|---|
| 本地输入反馈 | 40 | 16.7ms | 16.7ms | input处理至下一动画帧；不是物理按键延迟 |
| 动作搜索 | 30 | 184.8ms | 187.8ms | 输入至当前查询结果下一帧，含防抖 |
| 普通夹具选动作返回 | 30 | 505.3ms | 679.0ms | 点击至服务端持久确认及可编辑训练页 |
| 100001健康记录＋10000组 | 30 | 353.2ms | 491.5ms | 逐次增加为30个独立动作实例 |
| 1000001健康记录＋10000组 | 30 | 391.1ms | 550.7ms | 同上 |

[规模原始计时](../artifacts/master_redesign/training/scale.json)记录实际行数。两档各有一次额外导入失效测试样本，不能写成恰好100000/1000000行；各100场训练、10000组、46个动作。新进程启动至首次训练页分别3.833s、3.800s；浏览器导航至首次页分别1.452s、1.431s。主机192逻辑CPU、约2TB RAM、Python3.11.7，保留OS文件缓存；不能外推为普通手机硬件成绩。

可复跑脚本为 `tests/training/master_training_browser.py`、`master_training_scale.py`、`master_progress_browser.py`，以及原 `product_redesign_training_browser.py`。浏览器环境设置：

```bash
export PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin
export LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu
PYTHONPATH=tests/training .venv/bin/python tests/training/master_training_browser.py --output artifacts/master_redesign/training/after
```

已有训练定向回归247项通过（60.92s）。后续报告/导航合并回归结果以最终全量测试报告为准，不将这247项称作全应用通过。尚未验证真实iOS软键盘升降、Safari输入法/安全区、物理触控延迟、远程网络，以及浏览器数据被用户清除后的本机未同步草稿恢复；最后一种场景不能靠浏览器本地存储承诺恢复。
