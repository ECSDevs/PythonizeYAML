# 加载与导出

模块级函数对应常用的 PyYAML 入口。所有往返函数都委托给按需创建、进程级共享的默认引擎;若需要独立配置或线程隔离,请直接实例化 `YAML`。

名为 *stream* 的输入参数接受 `str`、UTF-8 `bytes`,或返回其中之一的带 `.read()` 方法的对象。

## `load()`

```python
load(stream, Loader=None)
```

使用无损往返引擎从 *stream* 加载第一个 YAML 文档。注释、标量样式、锚点、别名与布局都会附着在返回对象上,而不是被丢弃。

- **stream** —— YAML 源:一个 `str`、UTF-8 `bytes` 或可读流。
- **Loader** —— 为 PyYAML 迁移兼容而接受并被忽略;始终使用往返引擎。

返回一个 `Document`:映射与序列根对应 `DocumentMapping` 或 `DocumentSequence`(`dict` 与 `list` 的子类),标量根对应 `DocumentScalar`。输入不是合法 YAML 时抛出 `YAMLError` 子类(通常是 `ScannerError` 或 `ParserError`)。

```python
>>> import pythonizeyaml as yaml
>>> config = yaml.load("port: 8080\n")
>>> config["port"]
8080
```

## `load_all()`

```python
load_all(stream, Loader=None)
```

从 *stream* 加载每一个 YAML 文档。

- **stream** —— 要读取的 YAML 流。
- **Loader** —— 为 PyYAML 迁移兼容而接受并被忽略。

返回按源顺序排列的 `Document` 对象列表,每个文档对应一个元素。错误行为与 `load()` 相同。若更倾向于使用有序的 `DocumentStream` 包装,请使用 `load_documents()`。

```python
>>> for doc in yaml.load_all("---\nname: one\n---\nname: two\n"):
...     doc["name"]
'one'
'two'
```

## `dump()`

```python
dump(data, stream=None, *, indent=None, width=None, explicit_start=None,
     allow_unicode=None, default_flow_style=None, sort_keys=None,
     encoding=None, Dumper=None)
```

在保留原始布局的前提下把 *data* 序列化为 YAML。

- **data** —— 普通 Python 数据或 `Document`。传入 `Document` 时,`dump()` 委托给 `Document.dump()`:未经修改的文档精确回放源文本,修改过的节点以局部补丁方式应用。
- **stream** —— 可写流。为 `None`(默认)时返回 YAML 文本 `str`;否则写入 *stream* 并返回 `None`。
- **indent** —— (`int | None`)设置嵌套映射与序列的缩进宽度,并把序列偏移重置为零,近似 PyYAML 的 `indent` 行为。已加载的文档除非显式传入,否则保留原始布局。
- **width** —— (`int | None`)发射器为新数据选择布局时的首选最大行宽。
- **explicit_start** —— (`bool | None`)输出起始 `---` 文档标记。
- **allow_unicode**、**default_flow_style**、**sort_keys**、**encoding**、**Dumper** —— 为 PyYAML 迁移兼容而接受并被忽略,因为源布局与 Unicode 输出本来就会被保留。

其他任何关键字参数都会抛出 `TypeError`。

```python
>>> yaml.dump({"name": "demo"}, indent=4, explicit_start=True)
'---\nname: demo\n'
```

## `dump_all()`

```python
dump_all(documents, stream=None, *, indent=None, width=None,
         explicit_start=None, allow_unicode=None, default_flow_style=None,
         sort_keys=None, encoding=None, Dumper=None)
```

把文档可迭代对象序列化为多文档流,文档之间以 `---` 标记分隔。

- **documents** —— 可序列化为 YAML 的值或 `Document` 对象组成的可迭代对象。`load_documents()` 返回的 `DocumentStream` 也可以直接传入,在其文档均未修改时会精确回放。
- **stream** —— 与 `dump()` 相同的约定。
- 其余关键字参数 —— 与 `dump()` 相同。

生成器会在输出前被消费。不传 `explicit_start` 时,第一个文档不会带起始标记。

```python
>>> yaml.dump_all([{"name": "one"}, {"name": "two"}], explicit_start=True)
'---\nname: one\n---\nname: two\n'
```

## `safe_load()`

```python
safe_load(stream)
```

使用安全引擎加载第一个文档,返回不带文档包装的普通 Python 值。

- **stream** —— 要读取的 YAML 源。

返回普通的 `dict`、`list` 或标量。未知应用标签不会被解析为 Python 对象:形如 `!!python/object/apply:...` 的输入会抛出 `ConstructorError`,而不会执行任何内容。

```python
>>> yaml.safe_load("enabled: true\n")
{'enabled': True}
```

## `safe_load_all()`

```python
safe_load_all(stream)
```

使用安全引擎加载每一个文档。

- **stream** —— 要读取的 YAML 流。

返回普通 Python 值列表。标签限制与 `safe_load()` 相同。

## `safe_dump()`

```python
safe_dump(data, stream=None, *, indent=None, width=None, explicit_start=None,
          allow_unicode=None, default_flow_style=None, sort_keys=None,
          encoding=None, Dumper=None)
```

使用安全表示序列化 *data*;只会输出普通 YAML 类型。

- **data** —— 普通 Python 数据。*data* 中任何位置的 `Tagged` 值都会抛出 `RepresenterError`。
- **stream** —— 与 `dump()` 相同的约定。
- 其余关键字参数 —— 与 `dump()` 相同。

```python
>>> yaml.safe_dump({"enabled": True})
'enabled: true\n'
```

## `safe_dump_all()`

```python
safe_dump_all(documents, stream=None, *, indent=None, width=None,
              explicit_start=None, allow_unicode=None,
              default_flow_style=None, sort_keys=None, encoding=None,
              Dumper=None)
```

使用安全表示序列化文档可迭代对象。

- **documents** —— 由可序列化为普通 YAML 的值组成的可迭代对象。
- **stream** —— 与 `dump()` 相同的约定。
- 其余关键字参数 —— 与 `dump()` 相同。

## 显式的往返命名

```python
round_trip_load(stream, Loader=None)
round_trip_load_all(stream, Loader=None)
round_trip_dump(data, stream=None, **kwargs)
round_trip_dump_all(documents, stream=None, **kwargs)
```

分别是 `load()`、`load_all()`、`dump()` 与 `dump_all()` 的别名,供希望显式表达往返意图的调用点使用。

## 引擎对象

模块级函数共享每种风格各自的默认引擎。若要隔离配置或同时使用多套配置,请直接实例化 `YAML` 或 `SafeYAML`。

```python
YAML(config=None)
SafeYAML(config=None)
```

- **config** —— `IndentConfig` 或 `None`(使用 `DEFAULT_CONFIG`)。

`SafeYAML` 具有相同的方法,会拒绝非标准应用标签,并加载不带文档包装的普通 Python 值。

### `YAML.load(stream)`

加载第一个文档;返回 `Document`(`SafeYAML` 返回普通值)。

### `YAML.load_all(stream)`

加载每一个文档;返回 `Document` 对象列表(`SafeYAML` 返回普通值)。

### `YAML.dump(data, stream=None, *, config=None, explicit_start=None)`

序列化 *data*;可以接受 `Document` 对象。调用时传入的 *config*(`IndentConfig | None`)只在该次调用中覆盖引擎配置。

### `YAML.dump_all(documents, stream=None, *, config=None, explicit_start=None)`

序列化文档可迭代对象;可以接受 `DocumentStream`。*config* 覆盖行为与 `YAML.dump()` 相同。

```python
>>> engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
>>> engine.dump({"service": {"port": 8080}})
'service:\n    port: 8080\n'
```
