# 本轮界面参考与实施约束

2026-11-20 实际访问 GitHub 仓库、官方说明与以下五张官方截图，查看了图片内容。图片只保存在临时调研目录，没有复制进产品或仓库。实现独立编写，不采用其算法或素材。

|来源|实际观察|本项目采用|
|---|---|---|
|[Lift 首页](https://raw.githubusercontent.com/pawan67/lift/main/screenshots/home.png)|主数值、期间变化与单一柱形趋势占据上部；次级记录卡在下方|总览先显示本期真实事实与一张主趋势，取消装饰hero与目录|
|[Lift 训练](https://raw.githubusercontent.com/pawan67/lift/main/screenshots/session.png)|整页动作序列；每组负荷、次数、完成勾；历史数值较弱|整页纵向动作卡、输入标签、明确完成操作，历史参考不当作本次事实|
|[Lift 统计](https://raw.githubusercontent.com/pawan67/lift/main/screenshots/stats.png)|中性深色卡片、明确分组、次级分析入口|克制卡片与统一层级；不采用肌群热图或未经核实的组数评级|
|[Liftosaur 当前组](https://www.liftosaur.com/images/features/workout-screen/workout-screen-overview.webp)、[下一组](https://www.liftosaur.com/images/features/workout-screen/workout-screen-next-set.webp)|当前组较突出、输入大且可触达、历史带日期、完成后状态明确|当前输入组与完成组有边界/文字区别；日期历史与本次草稿分开|
|[Liftosaur 训练说明](https://www.liftosaur.com/features/workout-screen)|填写实际值后明确确认、逐组继续|采用明确完成本组与可选带入，不要求计划或程序|
|[shadcn 折线图](https://ui.shadcn.com/charts/line)|弱网格、清晰单位、悬停信息、卡片留白|现有 Plotly 使用相同信息层次；没有引入React组件库|

已打开 [Lift 仓库](https://github.com/pawan67/lift) 与 [Liftosaur 仓库](https://github.com/astashov/liftosaur)。主要视觉只参考 Lift，交互补充参考 Liftosaur。未复制 AGPL 实现或图片；无需把第三方UI代码混入 Python/Streamlit。

统一变量位于 `ui/assets/theme.css`，训练iframe使用对应局部变量。背景 #0B0F14、卡片 #141A22、边框 #2B3543、文字 #F1F5F9、次文字 #A3AFBF、强调 #38BFA3；主按钮为深色文字。系统无衬线、数字等宽、12–16px圆角、4/8px间距基础，触控44px，数字输入至少16px。正常、缺失、局部保存、失败、重试共用这些样式。

导航遵循本次产品合同，桌面顶部单行、手机顶部菜单。没有照搬任何参考的底部导航、侧栏、程序依赖、肌群恢复比例或健康评级。

基线为 `351822c`；旧 PR [#1](https://github.com/DonJonMao/apple/pull/1) 在核对时仍为 open draft，head `021f85559197996c950edafe8089049f3c461d93`，未合并。本轮仅复用经重新验证的定向改动。五份用户原有未跟踪PDF保留。
