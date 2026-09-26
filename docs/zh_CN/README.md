---
home: true
heroText: PythonizeYAML
tagline: 兼容 PyYAML、支持无损往返的 YAML 库。
actions:
  - text: 阅读教程
    link: /zh_CN/guide/
    type: primary
  - text: 浏览 API
    link: /zh_CN/api/
    type: secondary
features:
  - title: 无损往返
    details: 编辑值的同时保留注释、缩进、标量样式和文档布局。
  - title: 兼容 PyYAML 的 API
    details: 使用 load、dump、safe_load、safe_dump 等熟悉的函数加载与导出 YAML。
  - title: 样式感知的文档对象
    details: 通过 Document 和 NodeRef 显式编辑注释、标签、锚点、别名和格式。
---

PythonizeYAML 在文档被加载、修改并再次导出的过程中,保持原有源文件布局不变。

## 安装

```console
pip install pythonizeyaml
```

## 快速示例

```python
import pythonizeyaml as yaml

document = yaml.load("service:\n  port: 8080\n")
document["service"]["port"] = 9090
print(yaml.dump(document))
```

教程逐步讲解加载、编辑与样式感知编辑。API 参考为每个公开接口列出精确的签名、参数与类成员。
