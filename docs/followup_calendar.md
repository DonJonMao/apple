# R01 训练日历修复

状态：已修复。基线为 `00a35d2`，没有回退仓库或修改用户数据。真实完整应用在合成库上复现了“2026 年 11 月只剩 30 日”，失败断言、截图及日志均保留于 [before-r1](../artifacts/followup_20261127/calendar/before-r1/browser.json)。

`workbench.js` 现在用实际日期作为日期按钮的稳定身份；同一目录页的返回和关闭按钮也以控件角色区分。更新时一个旧节点最多匹配一次，并正确接续替换后的节点。仍沿用局部 DOM 更新，没有强制重建同一页面：输入草稿继续按工作区、会话、组保存在浏览器状态中，未变控件保留原节点和焦点。

[after-r2 浏览器回执](../artifacts/followup_20261127/calendar/after-r2/browser.json) 使用真实 Streamlit、TrainingService、SQLite 和 Chromium：

- 2026-02、2024-02、2026-11、2026-12 分别覆盖 28/29/30/31 天；核对完整日期集合、唯一性、星期标题、月初占位、逐日排列及可见尺寸。初次、重复渲染、跨月、今天、详情返回和刷新均通过。
- 在 390 和 1440 宽度真实点击 11 月 3/11/23 日，分别打开 1/2/3 个完成组的不同训练；核对选中日期、训练名称、真实会话 ID 和每组 UUID。不是只检查按钮存在。
- 日期键盘激活后原焦点节点仍连接且保持焦点。所有所测页面的同级 DOM 键无重复，目录搜索后两个返回/关闭按钮均保留。
- 实际开始训练、选动作即返回、填 32.5×8/RIR=0、再次添加、刷新恢复草稿、保存迟到回执时继续填写另一组、回月历再进入、结束训练均通过。数据库最终保存同一会话、两组完成、次数 8/11、RIR 0/0。
- 日历组件在 320/375/390/430/768/1440 均无内部横向溢出。手机和桌面日历、三日期详情、闰年二月及结束训练截图已逐张目视核对。截图中完整日历存在，日期分布和训练标记正确；长页截图不代替真实点击及数据库核对。

快速结构回归直接调用交付 JS 中的 `nodeKey`：[旧代码两项失败](../artifacts/followup_20261127/calendar/before-keys.txt)，[新代码与原动作选择回归通过](../artifacts/followup_20261127/calendar/after-keys-and-picker.txt)。`node --check` 与新增浏览器工具 Ruff 检查通过。每次浏览器回执保存受验文件的前后 SHA-256；没有将其他并行开发文件冒称为本专项的冻结源码。

原完整训练浏览器脚本另行通过：[full-flow-r1](../artifacts/followup_20261127/calendar/full-flow-r1/training-browser-results.json)。包括丢回执同请求幂等重试、真实修订冲突、非法次数局部报错、复制为草稿、未完成草稿不计完成量、长训练返回位置和六宽度检查。该轮与报告诊断有并行负载，记录的交互耗时不作为本轮最终性能验收。

复现命令：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
PYTHONPATH=src .venv/bin/python tools/followup_calendar_browser.py \
  --output artifacts/followup_20261127/calendar/new-run
node --test tests/training/strength_calendar_keys_check.cjs tests/training/strength_picker_events_check.cjs
```

保留的修复后首轮失败 `after-r1` 来自新验证工具把整数会话 ID 与字符串拼接，发生于真实日期和焦点验证通过之后；修复工具后完整重跑 `after-r2`。它不是产品通过证据。没有实体 iPhone、Safari、软键盘或人体有效性验证；这些与 Chromium 行为检查分开。
