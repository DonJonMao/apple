# 力量训练组件

`index.html`、`workbench.css`、`workbench.js` 是可直接运行的生产资源；没有 Node/npm 构建步骤、运行时 CDN、外部字体或额外开发服务器。Python 的 `training_workbench.py` 使用 Streamlit `components.declare_component(path=...)` 提供这些文件。安装包通过 `pyproject.toml` 的 package-data 包含资源。

前端使用 Streamlit v1 组件消息协议。它仅负责视图、输入与显式命令；`training_bridge.py` 验证命令并调用原有 `TrainingService`、事件修订与科学分析。REST 接口、token、CORS 及训练数据库不因组件改变。

主要视图为首页月历、开始面板、当前训练、动作选择、历史详情；备注、结束摘要、休息计时及原有高级管理为按需打开的次级视图。动作卡片只渲染一个完整组编辑器。只有显式打开建议才会调用建议服务；每秒计时仅更新文本。

浏览器 localStorage 的命名空间包含不透明数据库/用户身份，组草稿进一步使用 session UUID/set UUID。它保存未提交输入、当前视图和待回执命令，不向外部服务发送数据。草稿只有收到后端成功回执才称为“已保存”。清理浏览器存储会移除未提交输入；已经保存的数据库草稿仍可重新读取。

同一操作重试保留命令 `id` 与 payload；`delivery` 仅让 Streamlit 转交同一请求。成功回执只清除与已提交值相同的本地字段，提交之后的新输入继续保留。后续保存版本取真实操作回执，不借用较新的页面快照。发生版本冲突时先保留输入，用户可读取最新记录、核对对照，再明确选择使用该版本重新保存。

检查 JavaScript 语法：

```bash
node --check src/healthzip/ui/strength_component/workbench.js
```

真实浏览器验收另见项目交付文档与 `artifacts/strength_workbench/`。Streamlit AppTest 的 transport 夹具验证 Python 命令路径，不能替代组件 DOM、手机布局或键盘验收。
