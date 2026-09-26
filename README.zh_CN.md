# pythonizeyaml

[English](README.md) | 简体中文

`pythonizeyaml` 是一个提供 PyYAML 兼容 API 的 YAML 库,其无损往返引擎使用 Rust 实现。对未经修改的文档执行加载再导出,会还原出与源文本完全一致的内容,包括注释、空行、缩进、标量样式、文档标记、锚点以及多文档布局。

解析器和发射器通过 PyO3 与 Maturin 编译,不依赖任何 Python YAML 运行时库。

## 与其他 YAML 库的比较

下表对 `pythonizeyaml` 0.4.0 与 PyYAML、`yamltrip` 和 `ruamel.yaml` 进行了比较。

| 方面 | pythonizeyaml | PyYAML | yamltrip | ruamel.yaml |
|---|---|---|---|---|
| 主要定位 | 提供 PyYAML 风格的 YAML API,支持无损往返 | 通用 YAML 序列化器/解析器 | 保持格式的 YAML 文件编辑器与查询 API | 通用 YAML 库,具备强大的往返支持 |
| 主要 API | `load`、`load_all`、`dump`、`dump_all`、`safe_*`、`full_*`、`unsafe_*`、`YAML` | 同样以函数为主的 API,另提供更底层的 scanner/parser API | `load`/`loads` 返回 `Document`;不可变编辑,另有 `Editor` | 面向类实例的 `YAML()` API;旧式顶层函数已弃用 |
| Document API | `load`/`load_all` 返回可变的 `Document` 对象;`load_document`/`load_documents` 与 `read_document`/`read_documents` 是显式写法;样式编辑直接在值上进行 | 没有可变的文档包装;请使用 Python 值或底层 node/event | 以 `Document`/`Editor` 为核心的编辑与查询 API | `YAML().load()` 返回可变的 `CommentedMap`/`CommentedSeq` 文档 |
| 返回模型 | `Document` 根(`dict`/`list` 子类);嵌套值为标准 Python 标量、`RoundTripMap`/`List`/`Set`、`Decimal`、`Tagged` | 普通 Python 对象以及 YAML AST/event/token 对象 | 包裹普通 Python 值的 `Document` | `CommentedMap`、`CommentedSeq` 及标量子类 |
| 后端 | 通过 PyO3 调用的自研 Rust 解析器/发射器 | 纯 Python,另有可选的 LibYAML C 扩展 | 通过 Rust `yamlpath`/`yamlpatch` 使用 `tree-sitter-yaml` | Python,另有可选的 C 解析器 |
| 未修改文档的往返 | 与源文本完全一致,包括注释、空行、样式、标记与换行布局 | 不保证保留;输出会重新生成 | 打补丁式编辑,保留源文本与格式 | 往返模式下保留注释与样式,但输出仍由发射器控制 |
| 注释与空白 | 未修改的文档逐字节保留 | 丢失或被规范化 | 保留 | 通常会保留 |
| 缩进与流式风格 | 保留原始格式;可用显式 `IndentConfig` 覆盖 | 按导出器设置重新生成 | 保留 | 常规往返流程中会保留,缩进可配置 |
| 标量引号/样式 | 保留,包括冗余引号与块样式 | 会被重写 | 按原始源文本保留 | 保留,并支持 `preserve_quotes` |
| 修改模型 | 直接修改加载得到的 `Document` 对象(dict 风格/list 风格);未改动的字节保持原样 | 修改普通对象后整体重新生成 | 不可变的 `Document` 方法或可变的 `Editor`;最小化补丁 | 修改 `CommentedMap`/`CommentedSeq` 对象 |
| 样式编辑 API | 值上携带 `style`、`collection_style`、`chomping`、注释、标签、锚点;`set(...)` 原子应用多个字段 | 提供导出选项与底层 representer;没有源样式编辑 API | 路径/编辑器操作可保留选定的源格式 | 通过对象属性与 `YAML` 发射选项提供往返样式控制 |
| 结构编辑保真度 | 局部编辑以补丁方式应用;被替换/新增的子树可能按规范格式输出 | 整体重新生成 | 为最小化结构补丁而设计 | 对附属注释与格式的保留非常完整 |
| YAML schema | 默认采用与 PyYAML 一致的 YAML 1.1 resolver(`yes`/`no` 布尔值、`010` 八进制、`1:30` 六十进制);出现 `%YAML 1.2` 指令时切换为 YAML 1.2 core schema | 默认面向 YAML 1.1 的 resolver | 只关注可编辑的 YAML 值;不解释标签 | 默认 YAML 1.2 |
| 大整数 | 任意精度的 Python `int` | 任意精度的 Python `int` | 超出有符号 64 位范围时可能丢失精度 | 任意精度的 Python `int` |
| Decimal 值 | 恰好能以 binary64 表示的十进制数解析为 `float`;其余解析为 `Decimal`;`!!decimal` 强制为 `Decimal` | 通常为 `float`;需要自定义 constructor 才能得到 `Decimal` | 基础标量转换;没有针对大十进制数的特殊支持 | 通常为 `float`;需要自定义 representer/constructor 才能得到 `Decimal` |
| 未知/应用标签 | 以 `Tagged` 返回;从不执行 | 取决于 loader/constructor;不安全的 loader 可能构造 Python 对象 | 不解释 | 保留;constructor 可自定义行为 |
| 安全加载 | `safe_load` 拒绝非标准标签 | `safe_load` 使用 `SafeLoader` | 没有单独的安全/不安全对象构造模型 | `YAML(typ="safe")` 或安全加载 API |
| 锚点与别名 | 解析、保留,并解析为共享的 Python 对象 | 已解析;导出器可能输出锚点 | 能识别但在提取时不解析 | 解析并保留 |
| 多文档流 | 支持 | 支持 | 不支持 | 支持 |
| 自定义类 | 没有 constructor/representer 插件 API | `YAMLObject`、constructor、representer | 不支持自定义类序列化 | constructor、representer 与插件 |
| 事件/节点 | 没有公开的 scan/parse/event API | 完整的 scanner、parser、composer、node API | 以 tree/query/path API 替代 | 完整的 event/node API |
| 错误 | 与 PyYAML 兼容的异常层级 | PyYAML 异常层级 | `YAMLTripError` 异常层级 | ruamel 特有的 `YAMLError` 异常层级 |
| 编码 | 通过 `str`/`bytes`/流输入 UTF-8 | 由 reader 决定,支持多种 YAML 编码 | 仅 UTF-8 | 可配置,编码支持广泛 |
| 成熟度 | 全新自研实现的 0.4.0 版本 | 非常成熟,部署广泛 | 较新的专注型库,版本 0.4.x | 非常成熟的往返实现 |

最重要的实际差异:

- **与 PyYAML 相比:** `pythonizeyaml` 默认保留源文件布局,但它年轻得多,缺少 PyYAML 成熟的 event API、自定义 constructor 生态、更广的编码支持以及长期的兼容历史。与不安全的 PyYAML loader 不同,它不会执行 `!!python/...` 标签。
- **与 yamltrip 相比:** yamltrip 围绕通过 `Document`/`Editor` 编辑和查询 YAML 文件进行优化;它明确不支持多文档流、标签解释、锚点解析以及任意大小整数的保留。`pythonizeyaml` 提供 PyYAML 风格的数据 API 和更完整的 YAML 语义,但其结构编辑的补丁能力不如 yamltrip 那样专精。
- **与 ruamel.yaml 相比:** ruamel 是"可变、保留注释的 YAML 对象"这一路线的成熟参照。`pythonizeyaml` 则承诺对未修改的文档精确回放源文本,并采用 Rust 原生解析、`Decimal` 精度策略和 `Tagged` 值。它尚未提供 ruamel 的类注册、插件生态或同等深度的 YAML 一致性覆盖。

参考来源:[PyYAML 仓库](https://github.com/yaml/pyyaml)、
[yamltrip README](https://github.com/usethis-python/yamltrip) 与
[ruamel.yaml 仓库](https://github.com/pycontribs/ruamel-yaml)。

## 环境要求

- Python 3.10 或更新版本
- 从源码构建时需要 Rust 1.83 或更新版本
- 扩展开发需要 [Maturin](https://www.maturin.rs/) 1.15 或更新版本

## 安装

```console
pip install pythonizeyaml
```

源码检出时:

```console
poetry install
poetry run maturin develop
```

## 快速上手

```python
import pythonizeyaml as yaml

document = yaml.load(open("config.yaml", encoding="utf-8"))
document["service"]["port"] = 9090
text = yaml.dump(document)
```

只有被修改的标量会被重写,其余位置的注释和格式逐字节保持不变。传入可写流作为第二个参数即可直接写入:

```python
with open("config.yaml", "w", encoding="utf-8") as handle:
    yaml.dump(document, handle)
```

## 数值解析

整数使用 Python 任意精度的 `int`。十进制与指数字面量会与 IEEE 754 binary64 进行精确比较:

```python
from decimal import Decimal
import pythonizeyaml as yaml

assert type(yaml.load("value: 1.5\n")["value"]) is float
assert type(yaml.load("value: 0.1\n")["value"]) is Decimal
assert type(yaml.load("value: 1e400\n")["value"]) is Decimal
```

使用 `!!float` 可强制为 `float`,使用 `!!decimal` 可强制为 `Decimal`。

## 标签与安全性

YAML 的 core 与 common 标准标签都会被解析,包括 `!!binary`、`!!timestamp`、`!!set` 以及合并键。未知的应用标签以 `pythonizeyaml.Tagged(tag, value)` 返回,并在往返过程中保留其原始写法。

处理不受信任的 YAML 时,请使用 `safe_load` 或 `safe_load_all`。这两个函数会拒绝非标准标签,而不是构造任意的 Python 对象。

```python
value = yaml.safe_load("enabled: true\n")
```

`full_load`/`full_load_all` 返回普通数据并容忍未知标签(未知标签以惰性的 `Tagged` 值返回),`unsafe_load`/`unsafe_load_all` 是它们的正式文档别名。与本库的每个加载器一样,它们从不构造任意 Python 对象。

## API

模块暴露:

- `load`、`load_all`、`dump`、`dump_all`
- `safe_load`、`safe_load_all`、`safe_dump`、`safe_dump_all`
- `full_load`、`full_load_all`、`unsafe_load`、`unsafe_load_all`
- `round_trip_load`、`round_trip_load_all`、`round_trip_dump`、`round_trip_dump_all`
- `YAML`、`SafeYAML`、`IndentConfig`、`DEFAULT_CONFIG`、`Tagged`
- `Document`、`DocumentStream` 与 `Comments`
- `load_document`、`load_documents`、`read_document` 与 `read_documents`
- `ScalarStyle`、`CollectionStyle`、`Chomping` 与 `SourceSpan`
- `YAMLError` 及其与 PyYAML 兼容的子类

`Loader=`、`Dumper`、`sort_keys`、`default_flow_style`、`allow_unicode` 和 `encoding` 为迁移兼容而接受;在与无损输出冲突的地方会被忽略。

## 高级样式文档

`load()`、`load_all()` 与 `load_document()` 都返回可变的、样式感知的 `Document` 对象。加载得到的对象其值直接携带样式 API。若要显式控制注释、标量样式、集合样式、标签、锚点、别名、指令和文档标记,直接对读出的值设置即可:

```python
from pythonizeyaml import ScalarStyle, load_document

document = load_document("name: example\nitems:\n  - one\n  - two\n")
document["name"].style = ScalarStyle.DOUBLE
document["name"].comments.before = ["# service name"]
document["items"].collection_style = "flow"

text = document.dump()
```

`load_document()` 返回单个可变的 `Document`;`load_documents()` 返回列表式的 `DocumentStream`。集合根加载为 `DocumentMapping` 或 `DocumentSequence`(`dict`/`list` 子类),标量根加载为 `DocumentScalar`。文档内的每个值都是往返包装——`dict`/`list` 的子类,或标量自身类型的子类——与普通值的相等比较和哈希完全一致。被赋值的标量会被包装,普通 `dict`/`list` 会被转换,因此新建的子树可以立即设置样式。文档像被包装的 `dict`/`list` 一样编辑:`document["key"] = value`、`del document["key"]`、`document["items"].append(x)`。使用 `Document.new()` 可以从零创建带样式的文档。

值上暴露 `path`、`value`、`span`、`style`、`collection_style`、`chomping`、`block_indent_indicator`、`tag`、`anchor` 和 `comments`。`set(...)` 方法可原子地应用多个字段。样式变更在修改前会先校验;失败情形参见 `StyleError`、`PathError` 和 `AliasError`。`bool` 与 `None` 值保持原样(它们无法被子类化),是仅有的没有此 API 的加载标量。

仓库搭建、测试与贡献约定请参见 [`CONTRIBUTING.md`](CONTRIBUTING.zh_CN.md)。

## 缩进配置

`IndentConfig(mapping=2, sequence=2, offset=0, width=80, preserve_quotes=True)` 控制新建数据以及显式的重新排版请求。除非显式提供覆盖配置,加载的文档会保留其原始布局。

## 开发

```console
cargo test --manifest-path rust/Cargo.toml
poetry run maturin develop
poetry run pytest
poetry build
```

测试基于 `tests/fixtures/` 运行;新增的格式错误输入请放在 `tests/fixtures/invalid/` 下。

## 根级标量文档

根级标量加载为 `DocumentScalar` —— 一个保留源元数据和标量样式(引号、块标头)的 `Document` 包装,但它不是 `str`/`int` 的子类。它与被包装的值相等,并可通过 `str()`、`int()`、`float()` 和 `bool()` 进行转换;嵌套标量则是保留了原始样式与格式的普通 Python 值。
