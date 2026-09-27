# Pydantic 集成

可选的 Pydantic 集成把 Pydantic 模型映射到样式感知的 YAML 文档上，并保持加载/导出往返逐字节一致。当 `pydantic` 可导入时，包根导出 `YAMLModel`；当 `pydantic-settings` 可导入时，额外导出 `YAMLSettings`、`YAMLSettingsConfigDict` 与 `YAMLSettingsSource`。它们全部是懒加载的：导入 `pythonizeyaml` 既不需要也不触发 Pydantic 的导入。

```console
poetry add "pythonizeyaml[pydantic]"             # YAMLModel
poetry add "pythonizeyaml[pydantic-settings]"    # YAMLSettings（隐含 pydantic）
```

核心契约是经过校验的逐字节往返：

```python
>>> assert Model.model_validate_yaml(original).model_dump_yaml() == original
```

## `YAMLModel`

`pydantic.BaseModel` 的子类。校验接受 YAML 来源与文档；序列化返回样式感知的文档。

```python
>>> from pythonizeyaml import YAMLModel
>>> class Limits(YAMLModel):
...     upload: str
...     retries: int = 3
>>> class AppConfig(YAMLModel):
...     host: str
...     port: int = 8080
...     limits: Limits
>>> cfg = AppConfig.model_validate_yaml("host: db\nport: 5432\n")
>>> cfg.model_dump_yaml()
'host: db\nport: 5432\n'
```

### `model_validate(obj, *, strict=None, from_attributes=None, context=None, **kwargs)`

覆写的类方法。当 `obj` 是 `Document`（`pythonizeyaml.load` 的返回值）时，先扁平化用于校验，再把它*收养*为实例的样式锚点：实例通过该文档导出，保留其注释与样式。其他输入（普通 `dict`、`from_attributes` 对象等）原样转发给 Pydantic，不产生锚点。

- **obj** – `Document`，或 `BaseModel.model_validate` 接受的任何输入。
- **strict**、**from_attributes**、**context** – 透传给 Pydantic。
- **返回** – 校验后的 `YAMLModel` 实例。

被收养的文档此后归实例所有：模型变化时就地更新并再次导出。

### `model_validate_yaml(source, *, strict=None, from_attributes=None, context=None, **kwargs)`

用 round-trip 引擎解析 `source` 并校验第一个文档。

- **source** – `str`、`bytes`，或带 `.read()` 方法的流。
- **strict**、**from_attributes**、**context** – 透传给 Pydantic。
- **返回** – 以解析出的文档为样式锚点的实例。

畸形 YAML 抛出本库的 `ScannerError` / `ParserError`；多于一个文档的流抛出 `ComposerError`；空来源等价于空映射；非映射根由 Pydantic 报告为校验错误。声明字段上的未知应用标签校验失败；被忽略的额外键上的标签原样保留。

### `model_dump(*, pretty=False, **kwargs) -> Document`

不带关键字参数时，把当前字段值就地同步回锚点源文档并返回。未变化的子树逐字节保留；变化的值经容器的编辑路径重写，保留该条目的键样式与注释，新值使用默认样式。源文档中不存在的字段仅在其值不等于默认值时追加；模型未声明的键（被忽略的额外键）保留。

传入任何 Pydantic 关键字（`include`、`exclude`、`mode`、`by_alias` 等）则改为构建一个不带源样式的新文档。

传入 `pretty=True` 时改为重新生成文档——见 [Pretty 导出](#pretty-导出)。

- **返回** – 可编辑、可用普通文档 API 导出的 `Document`（`dict` 子类）。

### `model_dump_yaml(*, stream=None, encoding=None, pretty=False)`

把模型序列化为 YAML 文本。

- **stream** – 写入该流并返回 `None`。
- **encoding** – 返回 `bytes`（或向二进制流写入字节）。
- **pretty** – 重新生成文档，而不是在锚点文档上打补丁。
- **返回** – YAML 文本；给定 `encoding` 时为 `bytes`；写入流时为 `None`。

### Pretty 导出

`model_dump(pretty=True)` 与 `model_dump_yaml(pretty=True)` 不再在锚点源文档上打补丁，而是重新生成文档。共有四处变化：

- **声明顺序** – 映射键按模型字段声明顺序输出，并递归作用于嵌套模型（含序列内的模型项）。模型未声明的键按源文件顺序追加在声明字段之后。
- **补全默认值** – 所有声明字段都会出现；源文件缺失的字段以其当前（默认）值写出。
- **字段描述** – `Field(description=...)` 渲染为键上方的注释块，描述的每一行对应一条注释。
- **容器空行** – 在每个块级映射内，只要相邻两条目中任一为非空容器（有元素的映射或序列），就在两者之间插入一个空行。标量相邻与空容器保持紧凑；序列项之间不加空行。

```python
>>> from pydantic import Field
>>> class Server(YAMLModel):
...     host: str = Field("localhost", description="监听地址")
...     ports: list[int] = []
>>> class AppConfig(YAMLModel):
...     debug: bool = False
...     server: Server
...     name: str = "app"
>>> print(AppConfig.model_validate_yaml(
...     "name: myapp\nserver:\n  ports: [8080]\n").model_dump_yaml(pretty=True))
debug: false

server:
  # 监听地址
  host: localhost

  ports:
    - 8080

name: myapp
```

已有注释随键迁移——键上方的注释块、内联注释以及最后一个条目之后的尾部注释——重排后的文件保留其文档说明。与字段描述相同的注释不会重复；对重新校验后的输出再执行 `model_dump_yaml(pretty=True)` 会得到相同文本（pretty 是幂等的）。

Pretty 重新生成是一次重新发射，而不是逐字节补丁：仅注释随键迁移，标量引号、集合样式等其他版式选择按库默认样式重新输出。逐字节契约仅适用于默认的 `model_dump()`。pretty 与其他 Pydantic 关键字组合时，过滤后的值仍会排序、注释并加空行，但不补全默认值、不追加未声明键，也不迁移源注释。

### 往返边界

逐字节保证在校验不改变值时成立。以下情况会用默认样式重写受影响的条目：

- 值发生类型强转（如 `int` 字段收到带引号的 `"5432"`）；
- 校验之后修改了字段（新值被重新输出）；
- 向 `model_dump` 传入了 Pydantic 关键字（构建新文档）。

键序跟随源文档而非字段声明顺序；源文档缺失的字段保持缺失，除非运行时被设为非默认值。`pretty=True` 是有意提供的出口：按声明顺序重排键、补全默认值并重排空行（见 [Pretty 导出](#pretty-导出)）。

## `YAMLSettings`

`pydantic_settings.BaseSettings` 的子类，其配置源包含用 pythonizeyaml 自身解析器读取的 YAML 文件（从不导入 PyYAML）。

```python
>>> from pythonizeyaml import YAMLSettings, YAMLSettingsConfigDict
>>> class Settings(YAMLSettings):
...     model_config = YAMLSettingsConfigDict(yaml_file="app.yaml")
...     host: str
...     port: int = 8080
>>> Settings().model_dump_yaml() == Path("app.yaml").read_text()
True
```

### 来源优先级

init 值、环境变量、dotenv、YAML 文件、secrets 目录——遵循 BaseSettings 约定。可覆写 `settings_customise_sources` 自定义顺序。

实例把解析出的 YAML 文档作为样式锚点，因此 `model_dump_yaml()` 逐字节复现文件内容，只有更高优先级来源提供的值（或构造后修改的值）会在原位以默认样式重写。

### `YAMLSettingsConfigDict`

扩展了 `pydantic_settings.SettingsConfigDict`：

- **yaml_file** – 单个路径，或有序的路径序列。靠后的文件覆盖靠前文件的键。缺失的文件静默跳过。

其余键透传给 `SettingsConfigDict`。

### `YAMLSettingsSource`

配置源类。它继承内置的 `YamlConfigSettingsSource`，只替换文件解析器，因此支持相同的配置键（`yaml_file`、`yaml_file_encoding`、`yaml_config_section`、`deep_merge`）。需要自定义来源顺序时，在 `settings_customise_sources` 中实例化它。

缺失的文件静默跳过；非映射根抛出 `ValueError`；畸形 YAML 抛出本库的 `YAMLError` 子类。

## 错误

| 情形 | 异常 |
| --- | --- |
| 畸形 YAML | `ScannerError` / `ParserError`（`YAMLError` 子类） |
| 多于一个文档 | `ComposerError` |
| 声明字段上的未知标签 | Pydantic `ValidationError` |
| 字段校验失败 | Pydantic `ValidationError` |
| 设置文件非映射根 | `ValueError` |
| 设置文件缺失 | 静默跳过 |
