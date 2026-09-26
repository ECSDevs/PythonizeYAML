# 安全校验 CI 清单

假设有一个 CI 服务接受用户上传的 YAML 清单。校验器只需要普通的 YAML 值,因此应当在输入边界处拒绝应用特定的标签。

## 1. 创建校验器

创建 `validate_ci.py`:

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


if __name__ == "__main__":
    for problem in validate(Path("ci.yaml")):
        print(problem)
```

## 2. 测试有效输入

`ci.yaml` 可以包含普通的 YAML 值:

```yaml
steps:
  - run: python -m pytest
```

`safe_load()` 返回普通的 Python 映射和序列。它接受与 `load()` 相同的字符串、字节串和可读流输入。

## 3. 了解标签的处理方式

常规 API 会把未知标签保留为 `Tagged`,而不会执行它:

```python
value = yaml.load("job: !runner {name: tests}\n")
assert isinstance(value["job"], yaml.Tagged)
assert value["job"].tag == "!runner"
```

安全 API 对同样的输入会抛出 `ConstructorError`。跨越信任边界的数据请使用 `safe_load` 和 `safe_load_all`。`safe_dump` 和 `safe_dump_all` 同样会拒绝 `Tagged` 值。
