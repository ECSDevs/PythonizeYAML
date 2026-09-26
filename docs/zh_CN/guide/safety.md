# 加载不受信任的 YAML

来自用户、上传或第三方的 YAML 文件是输入,不是代码。本章展示如何在不构造任意 Python 对象的前提下读取它们、未知标签如何呈现,以及如何报告格式错误的输入。

## 1. 安全引擎

`safe_load()` 与 `safe_load_all()` 使用安全引擎。它们返回普通 Python 值——没有文档包装——并拒绝非标准应用标签,而不是解析它们:

```python
import pythonizeyaml as yaml

manifest = yaml.safe_load("steps:\n  - run: python -m pytest\n")
assert manifest == {"steps": [{"run": "python -m pytest"}]}
```

形如 `!!python/object/apply:os.system` 的输入会抛出 `ConstructorError`;不会有任何东西被执行。这使 `safe_load` 成为跨信任边界数据的默认选择。

对应的 `safe_dump()` 与 `safe_dump_all()` 只输出普通 YAML 类型,遇到 `Tagged` 值会以 `RepresenterError` 拒绝。

## 2. 校验器草图

把安全引擎与错误层级组合起来,就能为(例如)用户上传的 CI 清单写出简洁的校验器:

```python
from pathlib import Path
import pythonizeyaml as yaml


def validate(path: Path) -> list[str]:
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"invalid YAML: {error}"]

    problems = []
    if not isinstance(manifest, dict):
        problems.append("the document must be a mapping")
    elif "steps" not in manifest:
        problems.append("missing steps")
    return problems
```

捕获 `yaml.YAMLError` 即可覆盖整个层级——`ScannerError` 与 `ParserError` 对应格式错误的文本,`ConstructorError` 对应被拒绝的标签——且消息包含源位置:

```text
invalid YAML: tab characters must not be used in indentation
  in "unicode string", line 2, column 1
```

## 3. 常规引擎中的未知标签

往返引擎不会拒绝未知标签,因为逐字节保留文件正是它的职责。它把未知标签作为惰性的 `Tagged` 值返回:标签原文与解析出的值,不执行任何东西:

```python
value = yaml.load("job: !runner {name: tests}\n")
assert isinstance(value["job"], yaml.Tagged)
assert value["job"].tag == "!runner"
assert value["job"].value == {"name": "tests"}

assert yaml.dump(value) == "job: !runner {name: tests}\n"
```

`Tagged` 对象会原样往返,因此工具可以在不理解这些标签的情况下编辑这类文件——文件也不会丢掉它们。

## 4. 选择引擎

- 自己拥有并编辑的配置:`yaml.load()` —— 你会得到文档、样式与注释。
- 来自外部的数据:`yaml.safe_load()` —— 普通值,标签被拒绝。
- 含未知标签且必须原样保留的文件:`yaml.load()` 配合 `Tagged` 透传;或者当这类文件应当被直接拒绝时,使用 `safe_load()`。

两个引擎共享同一个解析器和同一套错误层级,所以一套 `except yaml.YAMLError` 策略对两者都有效。
