# 构建发布元数据命令

本示例更新一个小型 Python 项目使用的发布文件。加载得到的 `Document` 对修改值来说已经足够;同一个对象还暴露样式编辑能力,本命令用它处理注释、引号和集合样式。

## 1. 从一个发布文件开始

创建 `release.yaml`:

```yaml
# Published by release.py.
version: '0.3.0'
channel: stable
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
```

## 2. 加载文档并更新元数据

创建 `release.py`:

```python
from pathlib import Path

from pythonizeyaml import ScalarStyle, load_document


def publish(version: str) -> None:
    path = Path("release.yaml")
    document = load_document(path.read_text(encoding="utf-8"))

    document.node("version").update(
        value=version,
        style=ScalarStyle.SINGLE,
        inline="# Release version",
    )
    document.node("channel").comments.before = ["# Published channel"]
    path.write_text(document.dump(), encoding="utf-8")


if __name__ == "__main__":
    publish("0.4.0")
```

`NodeRef.update()` 会先校验所有请求的样式字段,再应用变更。如果后面的字段无效,文档会恢复到之前的状态。

## 3. 验证结果

运行 `python release.py` 会得到:

```yaml
# Published by release.py.
# Published channel
version: '0.4.0'  # Release version
channel: stable
artifacts:
  - pythonizeyaml
  - pythonizeyaml-docs
```

原有的引号样式得以保留,新的注释被挂载到具体的节点上。`document.source` 仍是原始源文本;当前的表示请使用 `document.dump()` 获取。

## 4. 添加带样式元数据的新字段

`Document.set()` 会创建缺失的映射路径,并返回一个 `NodeRef`:

```python
document.set(
    "build",
    "command",
    value="python -m build",
    style=ScalarStyle.DOUBLE,
    before="# Command used by CI",
)
```

如果希望某个集合以 `[pythonizeyaml, pythonizeyaml-docs]` 的形式输出,可以使用 `document.node("artifacts").collection_style = "flow"`。
