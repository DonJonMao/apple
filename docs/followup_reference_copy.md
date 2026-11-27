# 普通 STR-11 缺参考结果：只优化重复复制

`science/engine.py::_ordinary_reference_result` 在每次复用普通缺参考模板时仍核对参考资格、完整来源 ID、计数和结果契约。本次仅替换其两处模板深拷贝，不改正常 `evaluate`、指标算法／参考选择版本、逐结果 `validate_result`、缺参考的科学边界或历史冻结结果。

原单阶段 profile 中 10,000 次 helper 的累计 6.472 秒包含了约 5.185 秒 `deepcopy`。这是带剖析开销的结果，不直接等于无剖析的可节省墙钟。原证据保留在 [period-facts-profile-r1](../artifacts/followup_20261127/performance/period-facts-profile-r1/receipt.json)。

新增私有 `_clone_ordinary_reference_result` 只对精确的内建 `dict/list` 和 JSON 标量走简单路径：不可变标量直接复用，每次复制的 memo 保留结果内部别名，嵌套可变对象与模板／其他结果隔离。`tuple`、内建类型子类及其他值交给标准 `deepcopy(value, memo)`，保留原类型、元数据和共享引用关系；字符串子类作为字典键也不会被误当普通字符串复用。没有修改全局 `copy`，没有新增缓存、pickle、模式编译或通用 MetricResult 复制体系。结果继续执行原完整校验（包括禁止 NaN／Infinity 的 JSON 序列化）。

使用独立合成训练记录得到正常 STR-11 缺参考结果，进行九轮交替顺序的配对微基准，自动 GC 保持开启。当前样例的实际模板为 26 个字段；额外未来上下文排除记录保留在其中。源码、上下文、原始样本、运行环境和两次 profile 均见 [第二版回执](../artifacts/followup_20261127/performance/reference-clone-r2/receipt.json)。

| 阶段 | 每轮调用数 | 原实现中位耗时 | 新实现中位耗时 | 相对速度 |
|---|---:|---:|---:|---:|
| 仅复制模板 | 5,000 | 0.25220 秒 | 0.11567 秒 | 2.18 倍 |
| 完整普通参考 helper，含参考检查和结果校验 | 2,000 | 0.23496 秒 | 0.17217 秒 | 1.36 倍 |

另对各 2,000 次复制进行 cProfile：原实现调用 `deepcopy` 174,000 次（含递归），新实现调用私有克隆 24,000 次，普通模板无需标准深拷贝。新实现仍对每一个嵌套容器完成隔离，没有用浅拷贝省略工作。剖析数据与无剖析微基准分开，不能将 2.18 倍推广为整份报告提速。

第一版因每个容器内都执行局部 import，复制仅快约 4%；其 [r1 原始结果](../artifacts/followup_20261127/performance/reference-clone-r1/receipt.json)保留。第二版只在标准 fallback 才 import。两版受验 `engine.py` 快照均与当时记录 hash 一致，历史失败／低收益数据未覆盖。

测试覆盖标准深拷贝等价、嵌套 dict/list/tuple 类型、内部共享引用、兄弟结果／模板隔离、容器与字符串子类附加可变属性、字符串子类字典键，以及固定计算时刻下与正常 `evaluate` 的全字段相等（包括算法、参考版本与所有源记录身份）。不合法分母仍在每次结果校验中拒绝。既有普通参考批处理和力量契约专项合计 **111 通过，1.33 秒**；Ruff、差异检查通过，见 [最终检查](../artifacts/followup_20261127/performance/reference-clone-r2/checks-final.json)和 [JUnit](../artifacts/followup_20261127/performance/reference-clone-r2/tests-final.xml)。早一轮 110 项回执也保留。

本项没有执行全压力报告、真实浏览器或普通设备测量。整份报告的耗时与完整性仍由总交付后续实测决定；共享宿主机上的小型配对结果不代替性能验收。
