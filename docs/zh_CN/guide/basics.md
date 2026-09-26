# 加载与导出

本章介绍库的核心循环:把 YAML 读进可编辑的 Python 对象、再写回去,以及保证"没被修改的地方输出与输入完全一致"的往返保证。

## 1. 安装

```console
python -m pip install pythonizeyaml
```

示例统一使用与 PyYAML 一致的导入方式:

```python
import pythonizeyaml as yaml
```

## 2. 加载 YAML

`yaml.load()` 读取一个文档:

```python
document = yaml.load(
    """
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 8080
"""
)
```

返回值是一个 `Document`。映射与序列根对应 `dict` 或 `list` 的子类(`DocumentMapping`、`DocumentSequence`),所以你对 Python 容器的全部经验都适用:

```python
document["service"]["port"]     # 8080
len(document)                   # 1
"service" in document           # True
```

与 PyYAML 的差别在日常使用中看不出来,在底层却至关重要:这个对象记得每个值来自哪里——它的注释、引号、缩进——并且在你编辑时一直保留这份记忆。

`load()` 也接受 UTF-8 `bytes` 和任何带 `.read()` 方法的对象,因此文件句柄和网络响应无需预处理即可使用:

```python
with open("config.yaml", encoding="utf-8") as handle:
    document = yaml.load(handle)
```

## 3. 导出 YAML

`yaml.dump()` 是镜像操作。不传流时返回 YAML 文本;传入可写流则写入并返回 `None`:

```python
text = yaml.dump(document)

with open("out.yaml", "w", encoding="utf-8") as handle:
    yaml.dump(document, handle)
```

导出选项都是仅限关键字参数,并由所有导出函数共享:

```python
yaml.dump(data, indent=4)           # 嵌套缩进宽度,连字符与父键平齐
yaml.dump(data, width=100)          # 首选最大行宽
yaml.dump(data, explicit_start=True)  # 输出起始 ---
```

一些 PyYAML 关键字——`allow_unicode`、`default_flow_style`、`sort_keys`、`encoding`、`Dumper`——会被接受但忽略:它们与逐字节保留相冲突,而那正是本库的核心目标。其他任何关键字都会抛出 `TypeError`。

## 4. 往返保证

加载一个未经修改的文档再导出,结果与源文本完全一致:

```python
source = """\
# Published by release.py.
version: '0.3.0'
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
"""

assert yaml.dump(yaml.load(source)) == source
```

`0.3.0` 外面的单引号、块序列的连字符、注释和空行全部保留。修改一个值时,只有该值的字节会被重写——而且样式会保留,带引号的标量仍然带引号:

```python
document = yaml.load(source)
document["version"] = "0.4.0"

assert yaml.dump(document) == source.replace("'0.3.0'", "'0.4.0'")
```

## 5. 多文档流

一个文件可以包含多个以 `---` 分隔的 YAML 文档。`load_all()` 把它们作为 `Document` 对象列表返回,`dump_all()` 把列表写回流:

```python
documents = yaml.load_all(Path("environments.yaml").read_text(encoding="utf-8"))
for document in documents:
    document["service"]["port"] += 1

text = yaml.dump_all(documents)
```

如果希望把整个流当作一个对象——可以整体添加、插入或删除文档——请使用 `yaml.load_documents()`,它返回 `DocumentStream`;参见[API 参考](../api/documents.md#documentstream)。

## 6. 选择引擎

模块级函数共享进程级默认引擎。当你需要隔离的配置——不同的缩进,或一个可以重新配置而不影响全局状态的解析器——请实例化引擎类:

```python
engine = yaml.YAML(yaml.IndentConfig(mapping=4, sequence=4))
text = engine.dump({"service": {"port": 8080}})
```

`yaml.YAML` 做往返并返回文档;`yaml.SafeYAML` 具有相同的方法,加载普通 Python 值并拒绝非标准标签。后续章节对文档做就地编辑;[安全一章](./safety.md)讲解何时应选择安全引擎。
