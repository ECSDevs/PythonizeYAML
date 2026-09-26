# 配置、样式与标签值

用于配置输出、描述与编辑节点样式的公开值类型。它们都从包根导出。

## `IndentConfig`

```python
IndentConfig(mapping=2, sequence=2, offset=0, width=80, preserve_quotes=True)
```

不可变 dataclass,包含发射器必须自行选择布局时使用的缩进、行宽与引号保留设置:适用于 Python 中创建的数据、被替换的子树以及显式的重新排版请求。已加载的节点除非有覆盖,否则保留原始布局。

- **mapping** —— 嵌套映射的缩进宽度;必须 `>= 1`。
- **sequence** —— 嵌套序列的缩进宽度;必须 `>= 1`。
- **offset** —— 序列连字符相对父缩进的距离;必须 `>= 0` 且小于 *sequence*。
- **width** —— 首选最大行宽;必须 `>= 1`。
- **preserve_quotes** —— 往返时保留冗余的标量引号(`'x'` 与 `"x"`)。

无效组合会在构造时抛出 `ValueError`。

```python
>>> yaml.IndentConfig(offset=2)
Traceback (most recent call last):
    ...
ValueError: sequence offset must be smaller than the sequence indent
```

## `DEFAULT_CONFIG`

默认的 `IndentConfig()` 实例:两空格缩进,序列连字符与父键平齐,行宽 80,保留引号。

## `ScalarStyle`

```python
ScalarStyle(value)
```

描述标量书写方式的 `str` 枚举。接受从字符串构造,因此 `ScalarStyle("double")` 与 `ScalarStyle.DOUBLE` 是同一对象。

- **PLAIN**(`'plain'`)—— 不加引号;`key: value`。
- **SINGLE**(`'single'`)—— 单引号;`key: 'value'`。
- **DOUBLE**(`'double'`)—— 双引号;`key: "value"`。
- **LITERAL**(`'literal'`)—— 字面块样式;`key: |`。
- **FOLDED**(`'folded'`)—— 折叠块样式;`key: >`。

literal 与 folded 样式要求字符串值;`plain` 会拒绝普通写法会解析成其他 YAML 类型的字符串。

## `CollectionStyle`

描述映射与序列布局的 `str` 枚举。

- **BLOCK**(`'block'`)—— 每行一条的常规缩进形式。
- **FLOW**(`'flow'`)—— 行内 `{...}` / `[...]` 形式。

## `Chomping`

块标量末尾换行行为的 `str` 枚举。

- **CLIP**(`'clip'`)—— 默认;保留单个末尾换行。
- **STRIP**(`'strip'`)—— 输出为 `|-` 或 `>-`;不保留末尾换行。
- **KEEP**(`'keep'`)—— 输出为 `|+` 或 `>+`;保留全部末尾换行。

## `SourceSpan`

```python
SourceSpan(start, end, line, column)
```

不可变 dataclass,定位节点在原始文本中的位置;通过 `NodeRef.span` 在已加载文档上可用。

- **start** —— 节点起始字节偏移。
- **end** —— 节点结束后的字节偏移。
- **line** —— `start` 所在行号,从 1 开始计数。
- **column** —— `start` 所在列号,从 1 开始计数。

## `Tagged`

```python
Tagged(tag, value)
```

不可变的标签/值对,用于没有原生 Python 表示的应用级 YAML 标签。往返引擎会把未知标签作为 `Tagged` 返回,而不是执行或丢弃它们,并在输出时原样写回标签。

- **tag** —— 标签原文,含前导 `!`。
- **value** —— 标签下解析出的值。

`Tagged` 与标签和值都相同的另一个 `Tagged` 相等。

```python
>>> job = yaml.load("job: !runner {name: tests}\n")["job"]
>>> job.tag, job.value
('!runner', {'name': 'tests'})
```
