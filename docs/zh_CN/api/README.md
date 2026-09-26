# API 参考

PythonizeYAML 提供与 PyYAML 兼容的统一 API。`load()` 与 `load_all()` 返回样式感知的 `Document` 对象,它们同时表现得像被包装的普通 `dict` 与 `list`;`dump()` 与 `dump_all()` 可以直接接受这些文档。样式编辑就建立在这同一批对象之上。

参考文档按以下方式组织:

- [加载与导出](./functions.md) —— 模块级函数与 `YAML` / `SafeYAML` 引擎,附完整签名与逐参数说明。
- [文档与样式编辑](./documents.md) —— `Document` 类及其成员、`DocumentMapping` / `DocumentSequence` / `DocumentScalar` 子类、值上的样式 API、`Comments` 与 `DocumentStream`。
- [配置、样式与标签值](./styles.md) —— `IndentConfig`、`DEFAULT_CONFIG`、样式枚举、`SourceSpan` 与 `Tagged`。
- [错误](./errors.md) —— `YAMLError` 层级及各异常的触发场景。

如果你刚接触本库,请先阅读[教程](../guide/),再回到这里查阅精确签名。
