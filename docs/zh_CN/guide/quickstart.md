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

`load()` 接受字符串、字节串或可读流。默认加载器会把源元数据附着在映射和序列上,因此修改嵌套值后,`dump()` 会产生一次局部编辑。

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

`load_all()` 返回一个列表。当你需要把每个文档的注释、样式或文档标记当作一等属性处理时,请使用文档 API。
