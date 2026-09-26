# 错误

异常层级与 PyYAML 一致:包内抛出的每个错误都派生自 `YAMLError`,因此 `except yaml.YAMLError` 可以捕获全部。解析侧的错误携带源位置;其余错误描述路径、样式、别名与输出失败。

## 层级

```text
YAMLError
├── MarkedYAMLError
│   ├── ScannerError
│   ├── ParserError
│   ├── ComposerError
│   └── ConstructorError
├── EmitterError
├── RepresenterError
├── SerializerError
├── PathError
├── StyleError
└── AliasError
```

## `MarkedYAMLError`

携带 Rust 解析器源位置的错误基类。其 `str()` 是多行消息,末尾是形如 `  in "unicode string", line 1, column 7` 的位置标记。

- **context** —— 正在解析什么,或为 `None`。
- **context_mark** —— 外层结构开始的位置。
- **problem** —— 具体问题描述。
- **problem_mark** —— 发现问题的位置。
- **note** —— 附加说明,或为 `None`。

### `ScannerError`

词法失败:引号或括号未闭合、当前上下文出现非法字符,或缩进格式错误。

### `ParserError`

token 流不符合 YAML 语法,例如流式序列从未闭合。解析器还强制执行 128 层的嵌套深度上限(与 libyaml 默认值一致):嵌套更深的输入会抛出 `ParserError`,而不是耗尽调用栈。

### `ComposerError`

文档结构在构造前即不合法:别名 `*name` 没有匹配的锚点,或期望单个文档的输入中出现了多个文档。

### `ConstructorError`

无法构造值。重复映射键会抛出此错误;安全引擎也会对 `!!python/object/apply:...` 之类的非标准应用标签抛出此错误。

## `EmitterError`

原生发射器在写出 YAML 文本时失败。

## `RepresenterError`

值无法被表示。安全引擎在 `safe_dump()` 输入中出现 `Tagged` 值或自定义应用标签时抛出;把复数这类没有 YAML 表示的值输出到无法表示的位置时也会抛出。

## `SerializerError`

输出前的序列化步骤失败,例如映射键无法被表示:复数可以作为值输出,但用作映射键时会抛出 `SerializerError`。

## `PathError`

路径不存在。`Document.at()` 与 `Document.node()` 对缺失路径、`Document.remove()` 对根节点,以及在标量节点之下赋值时都会抛出。

```python
>>> yaml.load("a: 1\n").at("missing")
Traceback (most recent call last):
    ...
PathError: no YAML node at path ('missing',)
```

## `StyleError`

样式请求与值不匹配,或请求本身不合法:非字符串值使用 `single`/`double`/`literal`/`folded` 样式、对非块标量设置 chomping 或块缩进指示符、注释行缺少 `#`、标签不以 `!` 开头、锚点名非法,或行内注释跨越多行。

## `AliasError`

别名操作无法完成:移除仍被别名引用的节点、移除仍被引用的锚点,或跨两个文档建立别名。
