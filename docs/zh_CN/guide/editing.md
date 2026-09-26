# 编辑值

本章讲如何修改数据:读取嵌套值、对它们赋值、创建新节点以及调整序列——同时文件的其余部分保持逐字节一致。

## 1. 赋值就像普通 Python

加载得到的文档是 `dict` 或 `list` 子类,所以普通的赋值本身就是一次往返编辑:

```python
import pythonizeyaml as yaml

document = yaml.load("service:\n  host: 127.0.0.1\n  port: 8080\n")
document["service"]["port"] = 9090

assert yaml.dump(document) == "service:\n  host: 127.0.0.1\n  port: 9090\n"
```

只有 `8080` 这个标量被重写;键的顺序、缩进以及别处的注释都原样保留。

## 2. 路径与 `at()`

要程序化地访问——运行时计算的路径、深层查找——请使用 `Document.at()`。路径部分是映射键和序列索引,由外向内:

```python
document.at("service", "port")          # 9090
document.at("artifacts", 0)             # 列表第一项
document.at(("service", "port"))        # 也可以传元组
```

路径不存在时抛出 `PathError` 而不是返回 `None`,这让拼写错误和结构漂移无法悄悄溜过:

```python
from pythonizeyaml import PathError

try:
    document.at("service", "poort")
except PathError as error:
    print(error)  # no YAML node at path ('service', 'poort')
```

`document[key]` 与 `document.at(...)` 对标量返回普通 Python 值,对嵌套集合返回往返容器;两者都支持通过 `document[key] = value` 赋值。

## 3. 用 `set()` 创建和替换节点

赋值要求父节点已存在。`Document.set()` 则会沿路径创建缺失的映射键,在同一次调用中应用样式选项,并返回被写入节点的 `NodeRef`:

```python
document = yaml.load("service:\n  host: 127.0.0.1\n")
ref = document.set("service", "healthcheck", value="GET /health")
```

[下一章](./styles.md)的所有样式选项都可以一并传入——注释、引号、标签、锚点:

```python
document.set(
    "service", "timeout",
    value=30,
    inline="# seconds before we give up",
)
```

所有参数都会先校验再应用。无效组合会抛出 `StyleError`,文档保持原样。

## 4. 操作序列

序列有专门的操作,保证条目样式和源元数据与数据同步移动:

```python
document = yaml.load("artifacts:\n  - pythonizeyaml\n")

document.append("artifacts", value="pythonizeyaml-docs")
document.insert("artifacts", index=0, value="mirror")
removed = document.remove("artifacts", 0)
```

`append()` 与 `insert()` 接受与 `set()` 相同的样式选项,并返回受影响条目的 `NodeRef`。`remove()` 返回被移除的值,并且拒绝移除文档根节点以及仍被别名指向的节点。

## 5. 从零构建文档

`Document.new()` 用普通 Python 数据创建文档——适合生成那些看起来仍像手写的配置文件:

```python
document = yaml.Document.new(
    {
        "service": {"host": "127.0.0.1", "port": 8080},
        "artifacts": ["pythonizeyaml"],
    }
)
document.set("service", "debug", value=False, inline="# set true locally")

text = document.dump()
```

新数据没有源布局可保留,缩进由 [IndentConfig](../api/styles.md#indentconfig) 决定——默认两空格,序列连字符与父键平齐。

## 6. 输出为何无损

`dump()` 不会重新序列化数据。对未修改的文档,它逐字节回放原始源文本。对修改过的文档,它在原地打补丁:

- 未修改的子树保留精确的源字节,注释也包含在内。
- 被修改的标量只在自己的区间内重写。
- 被替换或新建的子树按当前 `IndentConfig` 以规范形式输出。

实际效果是:只改一个值的工具产出的 diff 只有一行变化,这正符合代码审查者和 `git blame` 的预期。
