# 文档与样式编辑

文档 API 把源元数据和变更操作暴露为 Python 对象。当工具需要控制注释、样式、标签、锚点、别名、文档标记或精确路径时,请使用它。

## 加载文档

```python
load_document(stream: Any) -> Document
load_documents(stream: Any) -> DocumentStream
read_document(path: str | Path) -> Document
read_documents(path: str | Path) -> DocumentStream
```

`load_*` 函数接受字符串、UTF-8 字节串和可读流;`read_*` 函数从文件系统路径读取 UTF-8 文本。`load_document()` 返回单个文档;`load_documents()` 保留有序的多文档流。

```python
document = yaml.load_document("name: demo\n")
document.node("name").comments.inline = "# Display name"
print(document.dump())
```

## `Document`

```python
Document.new(root: Any = None, *, config: IndentConfig | None = None) -> Document
Document.value: Any
Document.data: Any
Document.root: NodeRef
Document.source: str
Document.directives: list[str]
Document.explicit_start: bool
Document.explicit_end: bool
Document.at(*path: Any) -> Any
Document.node(*path: Any) -> NodeRef
Document.set(*path: Any, value: Any, style: ScalarStyle | str | None = None,
             collection_style: CollectionStyle | str | None = None,
             chomping: Chomping | str | None = None,
             block_indent_indicator: int | None = None,
             tag: str | None = None, anchor: str | None = None,
             before: str | Iterable[str] | None = None,
             inline: str | None = None,
             after: str | Iterable[str] | None = None) -> NodeRef
Document.append(*path: Any, value: Any, **style_options: Any) -> NodeRef
Document.insert(*path: Any, index: int, value: Any,
                **style_options: Any) -> NodeRef
Document.remove(*path: Any) -> Any
Document.alias(*path: Any, target: NodeRef | tuple[Any, ...],
               anchor: str | None = None) -> NodeRef
Document.dump(stream: Any = None, *, config: IndentConfig | None = None,
              explicit_start: bool | None = None) -> str | None
```

路径由映射键或序列索引组成。当路径不存在时,`at()` 会抛出 `PathError`。`set()` 可以创建缺失的映射路径、原子地应用样式选项,并返回新节点。`append()` 和 `insert()` 要求路径指向序列;`remove()` 会拒绝根节点以及仍被别名引用的节点。`alias()` 会创建共享别名,并在必要时生成锚点名。

`source` 是加载时的原始文本。`dump()` 返回文本或写入流。未经修改的加载文档会被精确回放;修改过的节点以局部补丁方式应用。`config` 和 `explicit_start` 会覆盖该次调用的输出行为。

```python
document = yaml.Document.new({"items": []})
document.append("items", value="first", style="single")
document.set("enabled", value=True, inline="# Feature flag")
print(document.dump())
```

## `NodeRef`

```python
NodeRef.path: tuple[Any, ...]
NodeRef.value: Any
NodeRef.span: SourceSpan | None
NodeRef.style: ScalarStyle | None
NodeRef.collection_style: CollectionStyle | None
NodeRef.chomping: Chomping | None
NodeRef.block_indent_indicator: int | None
NodeRef.tag: str | None
NodeRef.anchor: str | None
NodeRef.is_alias: bool
NodeRef.alias_target: NodeRef | None
NodeRef.comments: Comments
NodeRef.update(**values: Any) -> NodeRef
```

标量样式有 `plain`、`single`、`double`、`literal` 和 `folded`;集合样式有 `block` 和 `flow`。chomping 为 `clip`、`strip` 或 `keep`,只对 literal 和 folded 字符串生效。块缩进指示符必须是 1 到 9 的整数。标签必须以 `!` 开头,锚点名不能包含 YAML 指示字符。

`update()` 接受 `value`、所有样式属性、`tag`、`anchor`,以及注释字段 `before`、`inline` 和 `after`。未知字段会抛出 `TypeError`;无效组合会抛出 `StyleError`,且不会产生部分修改。

```python
ref = document.node("message")
ref.update(style="double", inline="# Shown to users")
print(ref.path, ref.value, ref.style)
```

## `Comments`

```python
Comments.before: list[str]
Comments.inline: str | None
Comments.after: list[str]
```

`before` 和 `after` 注释接受字符串或由多行组成的可迭代对象。每个非空行都必须带有前导 `#`。行内注释只能有一行。

## `DocumentStream`

```python
DocumentStream(documents: Iterable[Document] = (), *,
               source: str = "", handle: Any = None)
len(stream) -> int
stream[index] -> Document
stream.append(document: Document) -> None
stream.insert(index: int, document: Document) -> None
stream.remove(index: int) -> Document
stream.dump(stream: Any = None, *, config: IndentConfig | None = None,
            explicit_start: bool = True) -> str | None
```

`DocumentStream` 有序且可变。它的 `dump()` 方法会精确保留未修改的源流;否则按文档标记逐个输出每个文档。

## 配置与公开类型

```python
IndentConfig(mapping: int = 2, sequence: int = 2, offset: int = 0,
             width: int = 80, preserve_quotes: bool = True)
Tagged(tag: str, value: Any)
SourceSpan(start: int, end: int, line: int, column: int)
```

`IndentConfig` 会校验缩进和行宽为正数、偏移量非负且小于 `sequence`,并控制新建或显式重新排版的数据。`Tagged` 是未知应用标签的不可变表示。`SourceSpan` 报告字节偏移量以及从零开始计数的行号和列号。
