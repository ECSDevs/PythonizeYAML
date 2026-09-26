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

返回一个惰性生成器,按源顺序逐个产出 `Document` 对象。与 PyYAML 的 `load_all()` 一样,流在首次迭代时才被读取和解析,且生成器只能消费一次。错误行为与 `load()` 相同。若更倾向于使用有序的 `DocumentStream` 包装,请使用 `load_documents()`。

```python
>>> for doc in yaml.load_all("---\nname: one\n---\nname: two\n"):
...     doc["name"]
'one'
'two'
```

## `dump()`

```python
dump(data, stream=None, Dumper=None, *, indent=None, width=None,
     explicit_start=None, explicit_end=None, allow_unicode=None,
     default_flow_style=None, sort_keys=None, encoding=None)
```

在保留原始布局的前提下把 *data* 序列化为 YAML。

- **data** —— 普通 Python 数据或 `Document`。传入 `Document` 时,`dump()` 委托给 `Document.dump()`:未经修改的文档精确回放源文本,修改过的节点以局部补丁方式应用。传入从文档中读出的往返容器(例如 `document["outer"]`)时,只输出该节点自身的 YAML,并保留其源布局。
- **stream** —— 可写流。为 `None`(默认)时返回 YAML 文本 `str`;否则写入 *stream* 并返回 `None`。
- **indent** —— (`int | None`)设置嵌套映射与序列的缩进宽度,并把序列偏移重置为零,近似 PyYAML 的 `indent` 行为。已加载的文档除非显式传入,否则保留原始布局。
- **width** —— (`int | None`)发射器为新数据选择布局时的首选最大行宽。
- **explicit_start** —— (`bool | None`)输出起始 `---` 文档标记。
- **explicit_end** —— (`bool | None`)输出结尾 `...` 文档标记。
- **allow_unicode**、**default_flow_style**、**sort_keys**、**encoding** —— 为 PyYAML 迁移兼容而接受并被忽略,因为源布局与 Unicode 输出本来就会被保留。
- **Dumper** —— 为签名一致占据 PyYAML 的第三个位置参数槽,被忽略。

其他任何关键字参数都会抛出 `TypeError`。

```python
>>> yaml.dump({"name": "demo"}, indent=4, explicit_start=True)
'---\nname: demo\n'
```

## `dump_all()`

```python
dump_all(documents, stream=None, Dumper=None, *, indent=None, width=None,
         explicit_start=None, explicit_end=None, allow_unicode=None,
         default_flow_style=None, sort_keys=None, encoding=None)
```

把文档可迭代对象序列化为多文档流,文档之间以 `---` 标记分隔。

- **documents** —— 可序列化为 YAML 的值或 `Document` 对象组成的可迭代对象。`load_documents()` 返回的 `DocumentStream` 也可以直接传入,在其文档均未修改时会精确回放。
- **stream** —— 与 `dump()` 相同的约定。
- 其余关键字参数 —— 与 `dump()` 相同。

生成器会在输出前被消费。不传 `explicit_start` 时,第一个文档不会带起始标记;传入 `explicit_end` 时,每个文档都会以 `...` 结束。

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

返回一个惰性生成器,逐个产出普通 Python 值——流在首次迭代时才被读取和解析,且生成器只能消费一次。标签限制与 `safe_load()` 相同。

## `full_load()`

```python
full_load(stream)
```

把第一个文档加载为普通数据,并容忍未知标签。

- **stream** —— 要读取的 YAML 源。

返回不带文档包装的普通 `dict`、`list` 与标量值。与 `safe_load()` 不同,未知应用标签不会抛错:它们以惰性的 `Tagged` 值返回。本库从不根据标签构造任意 Python 对象——`!!python/object/apply:...` 之类与其他未知标签一样被包装,绝不会被执行。

```python
>>> yaml.full_load("job: !runner {name: tests}\n")
{'job': Tagged(tag='!runner', value={'name': 'tests'})}
```

## `full_load_all()`

```python
full_load_all(stream)
```

把每个文档加载为普通数据,并容忍未知标签。标签处理见 `full_load()`。返回一个惰性生成器。

## `unsafe_load()` 与 `unsafe_load_all()`

```python
unsafe_load(stream)
unsafe_load_all(stream)
```

`full_load()` 与 `full_load_all()` 的 PyYAML 签名别名(有正式文档说明)。PyYAML 的 `unsafe_load` 会根据标签构造任意 Python 对象;本库有意永不这样做,因此这些别名并不比 `full_load()` 更危险,仅为兼容而存在。

## `safe_dump()`

```python
safe_dump(data, stream=None, Dumper=None, *, indent=None, width=None,
          explicit_start=None, explicit_end=None, allow_unicode=None,
          default_flow_style=None, sort_keys=None, encoding=None)
```

使用安全表示序列化 *data*;只会输出普通 YAML 类型。

- **data** —— 普通 Python 数据。*data* 中任何位置的 `Tagged` 值都会抛出 `RepresenterError`;`Document` 中任何位置出现的自定义应用标签(`!runner` 风格)同样会被拒绝,而能解析为普通值的标准 `!!` 前缀标签仍然允许。
- **stream** —— 与 `dump()` 相同的约定。
- 其余关键字参数 —— 与 `dump()` 相同。

```python
>>> yaml.safe_dump({"enabled": True})
'enabled: true\n'
```

## `safe_dump_all()`

```python
safe_dump_all(documents, stream=None, Dumper=None, *, indent=None, width=None,
              explicit_start=None, explicit_end=None, allow_unicode=None,
              default_flow_style=None, sort_keys=None, encoding=None)
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

### `YAML.dump(data, stream=None, *, config=None, explicit_start=None, explicit_end=None)`

序列化 *data*;可以接受 `Document` 对象。调用时传入的 *config*(`IndentConfig | None`)只在该次调用中覆盖引擎配置。

### `YAML.dump_all(documents, stream=None, *, config=None, explicit_start=None, explicit_end=None)`

序列化文档可迭代对象;可以接受 `DocumentStream`。*config* 覆盖行为与 `YAML.dump()` 相同。

```python
>>> engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
>>> engine.dump({"service": {"port": 8080}})
'service:\n    port: 8080\n'
```
