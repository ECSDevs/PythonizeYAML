# 编辑服务配置

本示例为一个 Web 服务构建一个小型配置命令。该命令修改一个端口,但不会重写维护者在 `config.yaml` 中手工保存的注释和缩进。

## 1. 创建项目

```console
mkdir service-config
cd service-config
python -m pip install pythonizeyaml
```

创建 `config.yaml`:

```yaml
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 8080 # Change this for another local process.
```

## 2. 编写更新命令

创建 `set_port.py`:

```python
from pathlib import Path
import sys

import pythonizeyaml as yaml


def set_port(path: Path, port: int) -> None:
    document = yaml.load(path.read_text(encoding="utf-8"))
    document["service"]["port"] = port
    path.write_text(yaml.dump(document), encoding="utf-8")


if __name__ == "__main__":
    set_port(Path("config.yaml"), int(sys.argv[1]))
```

`load()` 接受字符串、字节串或可读流。它返回 `DocumentMapping` —— 一个样式感知的 `dict` 子类,因此嵌套赋值就像普通 Python 一样工作。`dump()` 接受该文档并只对修改过的值打补丁。

## 3. 运行它

```console
python set_port.py 9090
```

结果文件保留了原有的注释和布局:

```yaml
# Settings for the local web service.
service:
  host: 127.0.0.1
  port: 9090 # Change this for another local process.
```

## 4. 处理多个环境

对于每个环境对应一个文档的 YAML 流,请使用 `load_all()` 和 `dump_all()`:

```python
documents = yaml.load_all(Path("environments.yaml").read_text(encoding="utf-8"))
for document in documents:
    document["service"]["port"] += 1
Path("environments.yaml").write_text(yaml.dump_all(documents), encoding="utf-8")
```

`load_all()` 返回一个 `Document` 对象列表。每个文档都通过 `Document.node()` 把自己的注释、样式和文档标记暴露为一等属性;参见[文档与样式编辑](../api/documents.md)。
