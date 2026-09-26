# 加载与导出

函数 API 对应常用的 PyYAML 入口。默认函数使用无损往返引擎。输入函数接受 `str`、UTF-8 `bytes` 或带有 `.read()` 方法的对象。

## `load()`

```python
load(stream: Any, Loader: Any = None) -> Any
```

加载第一个文档。`Loader` 为迁移兼容而接受,会被忽略。可编辑的映射和序列会保留注释、样式、锚点、别名和源区间信息。

```python
config = yaml.load("port: 8080\n")
config["port"] = 9090
assert yaml.dump(config) == "port: 9090\n"
```

## `load_all()`

```python
load_all(stream: Any, Loader: Any = None) -> list[Any]
```

加载每一个文档并返回一个列表。`Loader` 会被接受并忽略。

```python
documents = yaml.load_all("---\nname: one\n---\nname: two\n")
documents[1]["name"] = "updated"
```

## `dump()`

```python
dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
```

当 `stream` 为 `None` 时返回 YAML 文本;否则写入可写流并返回 `None`。支持的选项包括:

```python
dump(data, stream=None, *, indent=None, width=None,
     explicit_start=None, allow_unicode=None,
     default_flow_style=None, sort_keys=None,
     encoding=None, Dumper=None) -> str | None
```

`indent` 设置映射与序列的缩进,并把序列偏移重置为零。`width` 设置首选行宽。`explicit_start=True` 会输出起始 `---`。`allow_unicode`、`default_flow_style`、`sort_keys`、`encoding` 和 `Dumper` 会被接受但忽略,因为源布局与 Unicode 输出本来就会被保留。其他关键字参数会抛出 `TypeError`。

```python
text = yaml.dump({"name": "demo"}, indent=4, explicit_start=True)
```

## `dump_all()`

```python
dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

序列化一个文档可迭代对象。它的流与关键字参数行为与 `dump()` 相同,并在输出前消费生成器。

```python
text = yaml.dump_all([{"name": "one"}, {"name": "two"}])
```

## 安全函数

```python
safe_load(stream: Any) -> Any
safe_load_all(stream: Any) -> list[Any]
safe_dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
safe_dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

安全加载会以 `ConstructorError` 拒绝非标准的应用标签。安全导出会以 `RepresenterError` 拒绝 `Tagged` 值。导出选项与流返回规则与常规函数一致。

```python
settings = yaml.safe_load("enabled: true\n")
safe_text = yaml.safe_dump(settings)
```

## 显式的往返命名

```python
round_trip_load(stream: Any, Loader: Any = None) -> Any
round_trip_load_all(stream: Any, Loader: Any = None) -> list[Any]
round_trip_dump(data: Any, stream: Any = None, **kwargs: Any) -> str | None
round_trip_dump_all(documents: Iterable[Any], stream: Any = None, **kwargs: Any) -> str | None
```

这些名称是常规无损函数的别名。

## 引擎对象

```python
YAML(config: IndentConfig | None = None)
YAML.load(self, stream: Any) -> Any
YAML.load_all(self, stream: Any) -> list[Any]
YAML.dump(self, data: Any, stream: Any = None, *,
          config: IndentConfig | None = None,
          explicit_start: bool | None = None) -> str | None
YAML.dump_all(self, documents: Iterable[Any], stream: Any = None, *,
              config: IndentConfig | None = None,
              explicit_start: bool | None = None) -> str | None
SafeYAML(config: IndentConfig | None = None)
```

`YAML` 把配置隔离在实例内部。`SafeYAML` 具有相同的方法,但会拒绝非标准标签。调用时传入的 `config` 会覆盖引擎的 `IndentConfig`。

```python
engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
text = engine.dump({"service": {"port": 8080}})
```
