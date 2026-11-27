# 最终真实页面验收（2026-11-27）

本轮在当前共享工作区运行真实 Streamlit 与 Chromium 158，仅使用新建的合成临时 SQLite。未读取或修改用户库、未跟踪 PDF、历史报告。浏览器禁用外网，远程模型调用为 0；测试结束后删除的只有本轮临时合成库。全部截图和失败回执保留。

验收脚本为 `tools/repair_delivery_browser.py`。每个页面检查 320／375／390／430／768／1440 像素宽度；手机高度 844、其余高度 1000。除主文档和 `stMain` 横向几何外，逐个检查可见关键数值与比较文字的 `scrollWidth/clientWidth`、`scrollHeight/clientHeight`，防止页面本身无横溢但文字已经被裁切。320／390／1440 保存真实截图；每个回执保存渲染身份、实际文字和前后完整源码／UI 资产 SHA-256。浏览器交互耗时不是专项性能验收，宿主机其他负载未测量。

## 最终回执

| 范围 | 回执 | 结果 |
|---|---|---|
| 最终代码：固定完整夹具、实际切换、报告下载、训练主页面 | [delivery-fixed-final/browser.json](../artifacts/repair_20261127/pages/delivery-fixed-final/browser.json) | 21 项通过；前后源码身份一致 |
| 补修前固定夹具历史回执 | [delivery-fixed-r3/browser.json](../artifacts/repair_20261127/pages/delivery-fixed-r3/browser.json) | 21 项通过；前后源码身份一致 |
| 空库：总览、心率、睡眠、体重、心肺、运动及 W6 | [delivery-empty-r1/browser.json](../artifacts/repair_20261127/pages/delivery-empty-r1/browser.json) | 7 页六宽度通过；前后源码身份一致 |
| 少量数据：同上七页 | [delivery-single-r1/browser.json](../artifacts/repair_20261127/pages/delivery-single-r1/browser.json) | 7 页六宽度通过；前后源码身份一致 |
| 最后补修：身体比较的自动箭头 | [delivery-metric-arrows-r1/browser.json](../artifacts/repair_20261127/pages/delivery-metric-arrows-r1/browser.json) | 6 项通过，三页六宽度且无自动箭头；前后源码身份一致 |

固定夹具的范围截止时间为 `2026-11-22T00:00:00+08:00`。初始总览、身体截图沿用 `tests/health_change_fixture.py`；来源切换测试在这些截图之后才向同一个合成库追加第二来源，原来源不变。

`delivery-fixed-final` 使用未修改的验收工具，包含最后的箭头及报告统计／覆盖渲染补修。与 `final-complete` 全量回归同时运行，并发情况已写入回执；只用于功能验收，不能据其交互时间得出性能结论。没有在此次运行期间更改 src、tests 或 tools。

## 真实操作与结果

- 总览显示“睡眠中位数 6.0 小时”，没有将它写为平均睡眠。
- 真实点击静息心率入口并选择自定义范围后，显示 64.0 bpm、较前期 +5.0 bpm、记录 7/7 天、日代表值中位数及 SDNN 30.0 ms；展开个人参考，显示 59.0 bpm。
- 在 390 宽度点击真实手机菜单，从身体到总览再回身体，“本月”范围仍保留。
- 点击主题 popover 到睡眠，显示 6.0 小时和较前期 −2.0 小时；实际切到截止前 24 小时得到 5.0 小时；选择尚无声明的主睡眠明确显示未知，随后恢复逐日口径成功。
- 实际筛选“合成第二手表”，原始 78.3755 显示为 78.4 bpm，64.0 消失；切回原来源，64.0 恢复、78.4 消失。未以隐藏来源文字冒充筛选。
- 最终代码实际生成周期报告并点击 Markdown 下载。下载 11,795 字节，与 SQLite 的冻结 Markdown 完全相等；SHA-256 为 `8537f02a35befaab49d0ad79a7fd8a028f476025a5d2342e5d89a48f70c437c2`。正文同时保留期间日代表值中位数、记录天数、数值和来源，摘录在 [report-coverage-excerpt.txt](../artifacts/repair_20261127/pages/delivery-fixed-final/report-coverage-excerpt.txt)。报告按本周显示记录 6/6 天；身体自定义 7 天为另一范围，显示 7/7 天，未将两种范围冒充同一身份。本夹具无设备能量记录，因此设备能量覆盖的有值分支由对应独立测试验证。
- 展开冻结问题并真实选择 W6，等待问题的实际 `fact_id` 改变，验证其内容来自该报告。
- 真实点击准备审计包及下载，得到 4,937,643 字节 `healthzip-frozen-audit-2`。仅以下载文件运行 `reconstruct_report`，报告 ID、Markdown 和所有冻结问题均与库内 `load_report` 相等；W6 仍有原始配对，6 个分析对象和 2 个内容对象完整保留。
- W4 缺训练条件页面保留实际记录、条件限制和下一步，没有把未知伪造为可比。
- 训练主页与录入页的主文档／`stMain` 六宽度全部无横溢。通过真实动作选择与输入填写 32.5×8、RIR=0，改变六次屏幕宽度后仍保留。iframe 内部布局、完整训练和断线恢复另见 `repair_performance_pages.md`，本轮补足外层主页面。
- 空库的心率／睡眠／体重／心肺不伪造指标卡；少量数据验证实际单点及不足比较的呈现。

## 修复中发现的真实裁切

[delivery-fixed-r1](../artifacts/repair_20261127/pages/delivery-fixed-r1/browser.json) 与 [delivery-fixed-r2](../artifacts/repair_20261127/pages/delivery-fixed-r2/browser.json) 在 320 宽度失败并保留 `failure.png`。当时总览卡内宽 104px，64.0 bpm 的实际文字宽 132px，比较文字宽 160px；文档没有横溢仍不能证明内容完整。

真实 DOM 显示 `stMetricValue`／`stMetricDelta` 及直属 Markdown 容器已经是 `white-space:normal`，但 Streamlit 在内层 `<p>` 仍应用 `nowrap`。`theme.css` 最终补充限定 Metric 内 Markdown 段落的换行规则，以及 delta 自动高度和固定箭头尺寸；没有缩小数值、隐藏单位或取消断言。r3 完整通过关键文字尺寸检查。320 总览少数单位会换行，390 目视检查数值、单位、比较文字完整可读。

主验收结束后的目视复核又发现：`st.metric` 根据 delta 字符串首字符推断箭头，`较前期 -2.0 小时` 因有中文前缀被画成向上。已在 `health_comparison.py`、`body_workspace.py` 显式设置当前 Streamlit 支持的 `delta_arrow="off"`，保留中性色与明确正负号。定向补验重新实际进入心率、睡眠及独立静息心率指标，检查真实 DOM 没有自动箭头，同时重验三页六宽度及截图。最终页面证据由 `delivery-fixed-final` 最新完整流程、empty-r1／single-r1 与 metric-arrows-r1 独立补验共同组成；r3 保留为此前代码的历史回执。各轮之间的源码哈希不同，分别记录，没有改写旧回执。最新 390 睡眠截图也经目视核对，负变化没有误导的上箭头。

## 首屏位置与未验证边界

下表是页面顶部到第一张真实 Plotly 图的 y 坐标，手机首屏高 844px。图已进入首屏不表示整张图都已显示。

| 页面 | 320 | 390 | 1440 |
|---|---:|---:|---:|
| 总览 | 865 | 801 | 625 |
| 心率 | 623 | 575 | 579 |
| 睡眠逐日 | 691 | 643 | 651 |
| 睡眠截止前 24h | 715 | 667 | 627 |
| 周期报告 | 740 | 655 | 603 |
| W4 缺条件 | 1229 | 1079 | 976 |

总览在 320／375 宽度第一图分别为 y=865／849，仍略低于首屏。W4 缺条件页手机第一图仍需滚动；报告完成后顶部保留周期摘要与图，完整生成正文与冻结依据在其下方。这些不是“全部首屏达标”。没有实体 iPhone、Safari、软键盘或真实移动网络设备验证；没有将 Chromium 的视口测试描述成真机结果。

复现示例：

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tools/repair_delivery_browser.py \
  --output artifacts/repair_20261127/pages/delivery-fixed-new \
  --concurrent-load 'No intentional concurrent acceptance run; other host load not measured.'
```

空库／少量数据使用 `--mode empty`／`--mode single`，每次使用新的输出目录，不覆盖历史失败。
