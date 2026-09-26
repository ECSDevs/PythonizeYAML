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

## 2. 读取嵌套值

嵌套读取就是链式下标——文档对标量返回普通 Python 值,对嵌套集合返回往返容器,所以同样的语法可以不断深入:

```python
document["service"]["port"]             # 9090
document["artifacts"][0]                # 列表第一项
```

`Document.get()` 是带回退值的 dict 式读取。元组或列表会按嵌套路径处理:

```python
document.get("service", {}).get("port")  # 9090
document.get(("service", "port"))        # 9090
document.get("missing", "fallback")      # "fallback"
```

直接下标让拼写错误无处藏身——路径不存在时抛出 `PathError`:

```python
from pythonizeyaml import PathError

try:
    document["service"]["poort"]
except PathError as error:
    print(error)  # no YAML node at path ('service', 'poort')
```

## 3. 创建和替换节点

赋值遵循普通 `dict` 语义:父节点必须已存在,中间层级先赋值容器即可逐层创建:

```python
document = yaml.load("service:\n  host: 127.0.0.1\n")
document["service"]["healthcheck"] = "GET /health"
```

样式、注释、标签与锚点直接在值上管理——见[下一章](./styles.md)。`set()` 在一次校验过的步骤里应用多个字段:

```python
document["service"]["timeout"] = 30
document["service"]["timeout"].set(
    inline="# seconds before we give up",
)
```

`set()` 会先校验所有内容再应用。无效组合抛出 `StyleError`,文档保持原样。

## 4. 操作序列

序列编辑就是对被包装容器做普通的 `list` 调用,文档会保证条目样式和源元数据与数据同步移动:

```python
document = yaml.load("artifacts:\n  - pythonizeyaml\n")

document["artifacts"].append("pythonizeyaml-docs")
document["artifacts"].insert(0, "mirror")
document["artifacts"].pop(0)
```

移除也可以用 `del`——映射键在文档本体上(`del document["key"]`),索引在容器上(`del document["items"][0]`)。移除节点时会连同它的注释、样式、标签与锚点一起丢弃,并且拒绝移除仍被别名指向的节点。

## 5. 从零构建文档

`Document.new()` 用普通 Python 数据创建文档——适合生成那些看起来仍像手写的配置文件:

```python
document = yaml.Document.new(
    {
        "service": {"host": "127.0.0.1", "port": 8080},
        "artifacts": ["pythonizeyaml"],
    }
)
document["service"]["debug"] = False
document["service"]["debug"].inline = "# set true locally"

text = document.dump()
```

新数据没有源布局可保留,缩进由 [IndentConfig](../api/styles.md#indentconfig) 决定——默认两空格,序列连字符与父键平齐。

## 6. 输出为何无损

`dump()` 不会重新序列化数据。对未修改的文档,它逐字节回放原始源文本。对修改过的文档,它在原地打补丁:

- 未修改的子树保留精确的源字节,注释也包含在内。
- 被修改的标量只在自己的区间内重写。
- 被替换或新建的子树按当前 `IndentConfig` 以规范形式输出。

实际效果是:只改一个值的工具产出的 diff 只有一行变化,这正符合代码审查者和 `git blame` 的预期。
