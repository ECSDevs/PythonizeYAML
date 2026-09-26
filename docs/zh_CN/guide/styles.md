# 注释、样式、标签与锚点

前几章编辑的是值。本章用同样的对象编辑 PyYAML 会丢掉的一切:注释、引号、块标量细节、集合布局、标签与锚点。这些能力都通过 `NodeRef` 视图使用,所以本章从它讲起。

## 1. 节点引用

`Document.node()` 返回一个 `NodeRef` —— 某个节点的稳定视图:

```python
import pythonizeyaml as yaml

document = yaml.load("version: '0.3.0'\nchannel: stable\n")
version = document.node("version")
```

`NodeRef` 不是值本身,而是指向位置的句柄。它暴露值(`version.value`)、源位置(`version.span`)、所有样式属性以及节点的注释。不带参数时,`document.node()` 是文档根。

## 2. 注释

注释存在于三个位置,并会在值编辑后保留:

```python
document.node("channel").comments.before = ["# Published channel"]
document.node("channel").comments.inline = "# stable or beta"
document.node("channel").comments.after = []  # 清空下方的注释
```

```yaml
# Published channel
channel: stable  # stable or beta
```

规则与 YAML 相同:`before` 与 `after` 接受字符串或行组成的可迭代对象,每个非空行都必须以 `#` 开头;`inline` 只能是一行。已加载的注释可以直接通过同样的属性读取,无需先赋值。

## 3. 标量样式

引号与块样式是节点的属性:

```python
document.node("version").style = "single"     # 让 '0.4.0' 保持引号
document.node("notes").style = "literal"      # 使用 | 的块样式
document.node("notes").chomping = "keep"      # | + 保留末尾换行
document.node("notes").block_indent_indicator = 2
```

- `style` 是 `plain`、`single`、`double`、`literal`、`folded` 之一(字符串会被转换为 `ScalarStyle` 枚举)。
- `chomping` 是 `clip`、`strip` 或 `keep`,只对 literal 和 folded 标量生效。
- `block_indent_indicator` 是 `|` 与 chomping 符号之间的数字,`1` 到 `9`。

校验会拒绝 YAML 无法表达的组合——用 `single` 引号包数字、对普通标量做 chomping——并抛出 `StyleError`;会改变解析类型的 plain 样式(例如把字符串 `"true"` 写成普通样式)同样会被拒绝。

## 4. 集合样式

映射与序列以同样的方式在块式与流式之间切换:

```python
document.node("artifacts").collection_style = "flow"
```

```yaml
artifacts: [pythonizeyaml, pythonizeyaml-docs]
```

流式要求内容能写在一行内;流式集合中出现多行字符串会抛出 `StyleError`,而不是产出非法 YAML。

## 5. 标签、锚点与别名

标签和锚点是节点属性;别名是指向锚点的独立节点:

```python
document.node("base").tag = "!custom"
document.node("base").anchor = "base-values"

document.alias("override", target=document.node("base"))
```

`alias()` 调用会在需要时为目标加锚点,并把该路径变成别名(`*base-values`)。在别名节点上,`is_alias` 为 `True`,`alias_target` 返回目标 `NodeRef`;在目标上,`anchor` 返回锚点名。移除仍被别名引用的锚点会抛出 `AliasError`——请先移除别名。

## 6. 文档级元数据

指令与文档标记是文档的属性:

```python
document.directives = ["%YAML 1.1"]
document.explicit_start = True
document.explicit_end = True
```

对 `directives` 赋值会整体替换;每一行都必须以 `%` 开头。两个布尔标记控制开头的 `---` 与结尾的 `...`。

## 7. 原子的多字段编辑

`NodeRef.update()` 一步完成多个经过校验的字段修改:

```python
document.node("version").update(
    value="0.4.0",
    style="double",
    inline="# release version",
)
```

全部修改会先整体校验;任何一个字段无效,文档就会恢复原状,什么都不会应用。未知字段名抛出 `TypeError`,能抓住静默赋值放过的拼写错误。`update()` 返回同一个 `NodeRef`,因此可以链式调用。

`Document`、`NodeRef` 等的完整成员列表见[参考文档](../api/documents.md)。下一章讨论加载内容不受信任的 YAML。
