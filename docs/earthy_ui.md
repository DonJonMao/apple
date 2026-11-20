# HealthZIP 暖色自然风格界面

用户确认将 Loam. 参考用于现有健康系统。此次改动把沙色、陶土色、橄榄色、衬线标题、自然照片和有机圆角应用于已有工作区，继续使用真实记录和原训练服务。不是新建工作室官网。

2026-11-20 最终隔离验收：Chromium 156.0.8078.4 全站 39 项、现有摘要回归 5 项均通过；报告核对的 48／49 个产品文件与资源在运行前后及完成后均匹配。17 个颜色样本最低对比度 4.52:1；无外网请求、无 JavaScript 错误。全部截图仅使用合成记录。

力量完整回归另有 22 项通过，共 66 项真实浏览器检查。整仓 134 个测试文件共 2061 项通过，另补最终 UI 回归 30 项；既定 `ruff check src app.py tests` 通过。Wheel 内 22 个公开资源与源码字节一致。现有 UI 服务已重启，UI/REST 均保持启用且运行；生产只读冒烟检查通过，身体、运动、训练和导入记录数量保持不变。最终回执见 [verification.json](../artifacts/earthy_ui/verification.json)、[测试分片](../artifacts/earthy_ui/pytest-shards.json) 和 [公开文件哈希](../artifacts/earthy_ui/files.sha256.json)。

## 设计映射

| 参考要求 | 健康系统中的实现 | 核对位置 |
|---|---|---|
| 沙色纸张、陶土/橄榄强调、暖墨正文 | 全站背景细点纹理、语义色变量、浅色表单；主要按钮采用较深陶土色保证小字可读 | `ui/assets/theme.css`、`strength_component/workbench.css` |
| Fraunces 标题、Inter 正文 | 随包托管的 WOFF2；中文衬线回退也随包提供；字体不依赖运行时公网 | `ui/assets/fonts/`、`strength_component/fonts/` |
| 叶片标记、黏性模糊导航、胶囊 CTA | HealthZIP 品牌与“记录训练”真实入口；所有 10 个工作区共用同一主区导航 | `ui/theme.py`、`.st-key-earthy_app_header` |
| 双列大标题、斜体重点、手绘下划线 | 首页中文记录主题、陶土色重点和内联 SVG 曲线；按钮进入现有力量与心率页 | `.st-key-earthy_overview_hero` |
| 有机形状自然摄影、浮层信息卡、背景色块 | 本地田野照片、叶片形圆角、橄榄装饰徽章；浮层显示实际最近记录日期或等待记录 | `overview-meadow.jpg`、`overview-meadow-source.json` |
| 深墨色四项统计带 | 最近身体/运动记录日期、运动次数、力量记录次数、已有数据项目；从当前数据库读取，不生成营销数字或健康评分 | `.st-key-earthy_overview_stats` |
| 四列项目卡与悬停反馈 | 睡眠、心率、运动、体重与有氧四个真实工作区入口；窄屏折行 | `.overview-workspace-card`、`earthy_open_*` |
| 编号与图标 | 四卡保留 01–04 顺序、暖色图标区与记录日期；图标使用本地 SVG | `ui/overview.py` |
| 清晰正文、充足间距、圆润卡片 | 周/月结论仍在对应明细前；表格、展开项、输入框和力量组件采用一致暖色 | `ui/workspace_summary.py`、全站 CSS |
| 深色页脚 | 本地私人记录说明与 HealthZIP 品牌 | `.earthy-footer` |
| 动效克制、键盘可用 | 按钮与卡片轻微悬停，`prefers-reduced-motion` 关闭过渡；主按钮、导航、力量输入保留可见焦点 | 两套 CSS 的 `:focus-visible` 与媒体查询 |

参考中的客户数量、生成耗时、工作室服务、团队价值观、虚构联系表单和社交链接没有对应的健康用途，页面改用真实健康入口、记录日期、数据范围和已有导入说明。不会把装饰照片当作用户健康资料或训练动作示范。无需 Tailwind、Google Fonts 或 Iconify CDN。

此次没有修改 SQLite schema、导入流程、当前分析缓存键、训练选择算法或删除/撤销业务。已有主区标题“训练与健康记录”、`main_workspace` 状态以及 10 个工作区继续保留。力量 iframe 的改动限于样式、字体和本地资源。中文衬线采用覆盖 744 个静态界面字符的本地子集；自定义名称中的其它字形使用系统回退。

## 可复跑验证

```bash
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
PYTHONPATH=src .venv/bin/python tests/training/earthy_ui_browser_check.py \
  --chromium /home/sn_maozhifang/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux-arm64/chrome-headless-shell \
  --output artifacts/earthy_ui
```

脚本在随机 loopback 端口启动完整 `app.py`，临时工作目录内用真实 ZIP 导入器和训练服务创建合成数据。生产 `.local`、真实 Apple 导出及私人知识库均不使用。浏览器阻断当前 loopback origin 之外的 HTTP(S)。运行前后对全部主题/首页/力量前端及字体、图片资源重新计算 SHA-256，源码变化则本轮失败。

| 验收内容 | 证据 |
|---|---|
| 10 个工作区均能切换、共有标题与主区导航、无异常面板 | `earthy-browser-results.json` 的 `all_ten_workspaces` |
| 每个工作区在 320/375/390/430/1440 宽度无外层横向溢出 | `widths_*`，包含 document/body/main 实测宽度 |
| 首页四卡真实进入对应工作区 | `four_real_workspace_cards` |
| 本地字体加载、真实图片解码、四项当前数据统计 | `local_photo_fonts_and_real_stats` |
| 日期完整可读、实际数值子段落使用 Fraunces | 首页各宽度的 `date_text_geometry`；逐项验证 MetricValue 内实际 `p` 字体 |
| 导航实际随主区滚动保持位置，具有模糊背景 | `sticky_blurred_header` 的滚动量、前后边界及 computed CSS |
| 主要正文、按钮、统计、力量输入与完成状态的可读性 | `contrast_*` 的 computed 前景、合成背景与 WCAG 对比值 |
| 主 CTA 与力量输入可见键盘焦点 | `keyboard_focus_*`，通过 Tab/Shift+Tab 进入焦点并记录 outline |
| 手机关闭侧栏后仍能重新打开导入设置 | `mobile_import_sidebar`，真实点击原生展开按钮、打开设置并检查 SQLite 路径输入可见，再关闭 |
| 睡眠周/月结论、已观察来源仍可读 | `sleep_week_and_month` |
| 真实动作选择、32.5 kg × 8 自由组保存、RIR 保持未知 | `real_strength_record_with_new_theme`；力量 iframe 的五宽度检查另记 `responsive_earthy_completed_set` |
| 无运行时公网请求、无 JavaScript 错误、运行前后源码一致 | 报告顶层 `external_requests`、`page_errors`、`sources_unchanged_during_run` |

新增第四项统计的集成回归保留原先普通训练保存断言，并核对空库“0 项”在一次真实力量记录后变为“1 项”。完整既有力量浏览器回归另覆盖草稿、保存/重试、删除与撤销，不以新主题检查替代。

逐项结果见 [全站报告](../artifacts/earthy_ui/earthy-browser-results.json) 和 [摘要回归报告](../artifacts/earthy_ui/summary/summary-browser-results.json)。手机侧栏能重新进入导入设置，完整日期在五种宽度下均落在统计区域内；各数值实际子段落使用 Fraunces，普通正文与说明使用 Inter。力量截图滚动到真实保存组，能看到 32.5 kg × 8、未知 RIR 和完成态。

截图均为合成记录：

- [桌面总览](../artifacts/earthy_ui/overview-desktop.png)、[首页完整内容](../artifacts/earthy_ui/overview-desktop-full.png)
- [手机总览](../artifacts/earthy_ui/overview-mobile.png)
- [手机睡眠周月分析](../artifacts/earthy_ui/sleep-mobile.png)
- [手机力量首页](../artifacts/earthy_ui/strength-home-mobile.png)
- [手机力量录入](../artifacts/earthy_ui/strength-record-mobile.png)
- [桌面力量录入](../artifacts/earthy_ui/strength-record-desktop.png)

## 验证边界

颜色检查基于浏览器 computed 色、祖先背景的 alpha 合成与祖先 opacity，抽样限定纯色正文、按钮和输入等；不把照片区域像素或抗锯齿后的单点颜色当作对比度结论。装饰性渐变、纸纹的细微像素差异不在此公式内。320–1440 是桌面 Chromium 的真实 CSS 视口验证；没有据此宣称验证实体 iPhone、Safari、原生软键盘、安全区或所有系统辅助技术。

本地照片保留公开来源、许可链接、下载日期与字节哈希；字体保留其 OFL 许可。公开工件不含健康数据、数据库、日志、用户 PDF 或凭证。
