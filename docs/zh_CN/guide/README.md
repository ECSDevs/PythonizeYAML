# 教程

本教程从零开始讲解 PythonizeYAML:加载与导出、就地编辑值、控制注释与样式,以及安全地加载不受信任的输入。每一章都建立在前几章之上,并在[API 参考](../api/)接手更深入的内容。

PythonizeYAML 是一个提供 PyYAML 兼容 API、内置无损往返引擎的 YAML 库:加载文档、修改一个值、再导出,只要是没有被触碰的部分,输出都会与原文件逐字节一致。

各章统一使用 `import pythonizeyaml as yaml`,因此示例读起来就像 PyYAML 代码。

1. [加载与导出](./basics.md) —— `load()`、`dump()`、文档对象与往返保证。
2. [编辑值](./editing.md) —— 路径、赋值、`set()`、序列操作以及从零构建文档。
3. [注释、样式、标签与锚点](./styles.md) —— 通过 `NodeRef` 暴露的样式感知编辑层。
4. [加载不受信任的 YAML](./safety.md) —— `safe_load()`、`Tagged` 与信任边界上的错误处理。

想要完整可运行的项目而不是零散片段时,请看实战示例:

- [编辑服务配置](./quickstart.md)
- [构建发布元数据命令](./round-trips.md)
