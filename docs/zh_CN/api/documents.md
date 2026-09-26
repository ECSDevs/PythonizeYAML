# 文档与样式编辑

每一次无损加载都会返回一个 `Document` —— 一个样式感知的对象,同时表现得像它包装的普通 `dict`、`list` 或标量。本页是该对象模型的参考:`Document` 类、`NodeRef` 样式视图、注释访问以及多文档流。

## `Document`

```python
class Document(data, *, handle=None, root_id=-1, source='', config=None)
```

一个可变的、样式感知的 YAML 文档。应用代码通常通过 `load()`、`load_all()` 或 `load_document()` 获得 `Document`,而不是直接构造;要用 Python 数据构建文档,请使用 `Document.new()`。

- **data** —— 根 Python 值:映射、序列或标量。文档会就地对它进行修改。
- **handle** —— 支撑该文档的原生解析句柄(从 YAML 文本加载时才有)。句柄为未修改的节点提供源元数据(区间、样式、锚点、指令)。
- **root_id** —— 根节点在 *handle* 中的节点 id;没有句柄时为 `-1`。
- **source** —— 原始 YAML 文本,用于逐字节精确回放与局部补丁。给定 *handle* 时会被忽略。
- **config** —— `IndentConfig`,作为没有源布局的节点的输出回退配置。默认为 `DEFAULT_CONFIG`。

`Document` 还实现了其根值对应的容器协议:`len()`、迭代、`document[key]` 与 `document[key] = value`(分别委托给 `at()`/`set()`),映射根还支持 `keys()`、`items()` 与 `values()`——其中 `items()` 与 `values()` 会把别名条目穿透读取为其目标值。`str(document)` 对标量根返回被包装的标量,对容器根返回导出的 YAML 文本;`copy.deepcopy(document)` 返回完全独立的副本(带句柄的文档会从其导出文本重新加载,保留逐字节一致的格式)。标量根可通过 `str()`、`int()`、`float()`、`complex()` 与 `bool()` 进行转换。

### `Document.new(root=None, *, config=None)`

类方法,返回包装 *root*(默认 `None`)的新 `Document`。新建数据没有源布局,`dump()` 会按 *config* 输出。

### `Document.value`

文档根值,为 Python 标量或往返容器。对 `value` 赋值会替换整个根。

### `Document.data`

文档根值。`Document.value` 的只读孪生属性,便于在就地修改返回容器的调用点上表达意图。通过 `alias()` 创建的别名条目会穿透读取为目标值的当前状态:只要注册了任何别名,返回的映射/序列就是一份浅层解析副本而非原容器;没有别名时,返回的就是底层数据对象本身。

### `Document.root`

文档根的 `NodeRef`(`path == ()`),可用于访问文档级注释、样式、标签与锚点。

### `Document.source`

加载时的原始文本。用 `Document.new()` 创建的文档为空字符串。

### `Document.directives`

第一个文档前的指令行(例如 `["%YAML 1.1"]`)。赋值一个列表即整体替换;每一行都必须以 `%` 开头,否则抛出 `StyleError`。

### `Document.explicit_start`

文档是否以显式 `---` 标记开始。赋一个 `bool` 可覆盖源文件的状态。

### `Document.explicit_end`

文档是否以显式 `...` 标记结束。赋一个 `bool` 可覆盖源文件的状态。

### `Document.at(*path)`

返回 *path* 处的值。

- **\\*path** —— 一个或多个路径部分:映射键或序列索引,由外向内。也可以只传一个元组或列表代替多个参数。

路径不存在时抛出 `PathError`。别名节点会解析为目标值:通过 `alias()` 创建的条目穿透读取为目标值的当前状态,而源自源文件的别名与其目标共享同一个 Python 对象。

```python
>>> document = yaml.load("service:\n  ports: [8080, 8081]\n")
>>> document.at("service", "ports", 0)
8080
```

### `Document.node(*path)`

返回 *path* 处节点的 `NodeRef` 视图。不带参数时返回根节点。路径不存在时抛出 `PathError`。

### `Document.set(*path, value, style=None, collection_style=None, chomping=None, block_indent_indicator=None, tag=None, anchor=None, before=None, inline=None, after=None)`

把 *path* 处的节点设置为 *value*,并可在同一步原子地应用样式元数据。缺失的中间映射键会被创建。

- **\\*path** —— 要设置的节点的路径部分。
- **value** —— 新的 Python 值。
- **style** —— (`ScalarStyle | str | None`)标量样式:`plain`、`single`、`double`、`literal` 或 `folded`。字符串会被强制转换。
- **collection_style** —— (`CollectionStyle | str | None`)`block` 或 `flow`。
- **chomping** —— (`Chomping | str | None`)`clip`、`strip` 或 `keep`;要求 literal 或 folded 样式。
- **block_indent_indicator** —— (`int | None`)块标量的显式缩进指示符,`1` 到 `9`。
- **tag** —— (`str | None`)节点标签;必须以 `!` 开头。
- **anchor** —— (`str | None`)锚点名;不能包含 YAML 指示字符。
- **before**、**after** —— (`str | Iterable[str] | None`)放在条目前或条目后的注释行。每个非空行都必须以 `#` 开头。
- **inline** —— (`str | None`)放在值之后的单行注释。

所有参数都会先校验再应用;无效组合会抛出 `StyleError` 且文档保持不变。返回被写入节点的 `NodeRef`。

```python
>>> document = yaml.Document.new({})
>>> document.set("build", "command", value="python -m build", style="double")
NodeRef(path=('build', 'command'))
```

### `Document.append(*path, value, **style_options)`

把 *value* 追加到 *path* 处的序列,并返回新条目的 `NodeRef`。*path* 必须指向 `list`,否则抛出 `StyleError`。*style_options* 与 `Document.set()` 的样式关键字相同。

### `Document.insert(*path, index, value, **style_options)`

把 *value* 插入 *path* 处序列的 *index* 位置之前,其后元素依次后移,并返回新条目的 `NodeRef`。

- **index** —— 插入位置。

### `Document.remove(*path)`

移除 *path* 处的节点并返回其值。

- **\\*path** —— 要移除节点的路径部分;根节点不可移除。

路径不存在时抛出 `PathError`;节点仍有别名指向它时抛出 `AliasError`。附着在被移除子树上的样式覆盖会被丢弃。

### `Document.alias(*path, target, anchor=None)`

把 *path* 处的节点变成 *target* 的别名。*path* 既可以已经存在(其当前值成为别名),也可以是全新路径——缺失的中间映射键会被创建,新条目以别名形式持有目标值。

- **\\*path** —— 要成为别名的节点的路径部分。
- **target** —— 同一文档中的 `NodeRef`,或指向锚点源的路径元组。跨文档取别名会抛出 `AliasError`。
- **anchor** —— (`str | None`)附加到目标上的锚点名。省略且目标没有锚点时,会自动生成空闲名称(`id001`、`id002`……)。

返回别名节点的 `NodeRef`;其上可用 `is_alias` 与 `alias_target`。锚点本身在目标节点上。

```python
>>> document = yaml.load("default: 1\noverride: 2\n")
>>> document.alias("override", target=document.node("default"))
NodeRef(path=('override',))
>>> document.dump()
'default: &id001 1\noverride: *id001\n'
```

### `Document.dump(stream=None, *, config=None, explicit_start=None, explicit_end=None)`

输出文档。

- **stream** —— 可写流,或 `None` 以返回文本。
- **config** —— (`IndentConfig | None`)该次调用的输出覆盖。
- **explicit_start**、**explicit_end** —— (`bool | None`)该次调用的标记覆盖;省略时应用文档属性。

未经修改的加载文档会精确回放源文本;修改过的节点以局部补丁方式应用,被替换或新建的子树按 *config* 以规范形式输出。

## `DocumentMapping`、`DocumentSequence` 与 `DocumentScalar`

```python
DocumentMapping(data, *, ...)
DocumentSequence(data, *, ...)
DocumentScalar(data, *, ...)
```

`load()`、`load_all()` 与 `load_document()` 按根节点类型返回的 `Document` 具体子类。关键字参数与 `Document` 构造函数一致。每个子类都继承全部 `Document` 成员,同时表现得像被包装的值,因此可以直接替代普通的 `dict`、`list` 或标量:

- **DocumentMapping** —— `dict` 的子类;与普通映射及其他文档相等比较。
- **DocumentSequence** —— `list` 的子类。
- **DocumentScalar** —— 标量包装;与被包装的值相等比较,并可通过 `str()`、`int()`、`float()`、`complex()` 与 `bool()` 转换。标量根会保留其原始样式与格式,包括引号和块标头。

```python
>>> document = yaml.load("'0.3.0'\n")
>>> document == "0.3.0", document.root.style
(True, <ScalarStyle.SINGLE: 'single'>)
```

## `NodeRef`

`Document` 中某个节点的稳定视图,由 `Document.node()`、`Document.set()`、`Document.append()`、`Document.insert()` 与 `Document.alias()` 返回。视图按节点身份解析,而不是冻结的路径:当列表插入或删除使兄弟节点位移后,访问该 ref 仍会到达同一个节点;若 ref 指向的节点已被移除,再访问会抛出 `PathError`。在 Python 中新建的节点(没有原生节点 id)则回退为创建 ref 时使用的路径。属性赋值会先按节点的值校验请求的样式,再进行修改。

### `NodeRef.path`

标识该节点的路径部分 `tuple`——即该节点*当前*的路径,每次访问都按身份重新解析。

### `NodeRef.value`

节点的 Python 值。赋值会替换该值;若节点已附有样式,会先按新值校验。

### `NodeRef.span`

`SourceSpan`,给出节点在原始文本中的字节偏移与从 1 开始计数的行号/列号;没有源元数据的节点为 `None`。

### `NodeRef.style`

标量样式(`ScalarStyle | None`):`plain`、`single`、`double`、`literal` 或 `folded`。赋一个与值不匹配的样式会抛出 `StyleError`。

### `NodeRef.collection_style`

集合样式(`CollectionStyle | None`):`block` 或 `flow`。仅对映射和序列有意义。

### `NodeRef.chomping`

chomping 指示符(`Chomping | None`):`clip`、`strip` 或 `keep`。只有 literal 和 folded 标量能携带;赋给其他样式会抛出 `StyleError`。赋 `None` 可清除覆盖。

### `NodeRef.block_indent_indicator`

块标量的显式缩进指示符(`int | None`,`1`–`9`)。赋 `None` 可清除。

### `NodeRef.tag`

节点标签(`str | None`)。赋值必须以 `!` 开头。

### `NodeRef.anchor`

锚点名(`str | None`)。重命名锚点会同步改写指向它的别名;移除仍被别名引用的锚点会抛出 `AliasError`。

### `NodeRef.is_alias`

该节点是否为其他节点的别名(`*name`)。

### `NodeRef.alias_target`

该别名指向的锚点的 `NodeRef`;不是别名时为 `None`。

### `NodeRef.comments`

该节点条目的 `Comments` 视图。

### `NodeRef.update(**values)`

一步原子地应用多个字段,并返回同一个 `NodeRef`。

- **\\*\\*values** —— `value`、`style`、`collection_style`、`chomping`、`block_indent_indicator`、`tag`、`anchor`、`before`、`inline`、`after` 的任意组合,语义与对应属性及注释字段一致。

未知字段抛出 `TypeError`;无效组合抛出 `StyleError` 且文档恢复原状,因此更新不会部分生效。

```python
>>> ref = document.node("message")
>>> ref.update(style="double", inline="# shown to users") is ref
True
```

## `Comments`

通过 `NodeRef.comments` 访问。注释存储在拥有该节点的映射条目或序列项上,因此会在值编辑后保留。

### `Comments.before`

条目上方的注释行(`list[str]`)。接受字符串或行组成的可迭代对象;每个非空行都必须以 `#` 开头。

### `Comments.inline`

与值同行的注释(`str | None`)。必须是以 `#` 开头的单行。

### `Comments.after`

条目下方、下一个兄弟条目之前的注释行(`list[str]`),规则与 `Comments.before` 相同。

```python
>>> document.node("channel").comments.before = ["# Published channel"]
```

## `DocumentStream`

```python
DocumentStream(documents=(), *, source='', handle=None)
```

有序且可变的 `Document` 集合,由 `load_documents()` 与 `read_documents()` 返回。支持 `len()`、迭代与 `stream[index]`。

- **documents** —— 初始 `Document` 对象。
- **source** —— 原始流文本,在没有任何文档被修改时精确回放。
- **handle** —— 支撑该流的原生句柄。

### `DocumentStream.append(document)`

把 *document* 追加到末尾。传入非 `Document` 时抛出 `TypeError`。

### `DocumentStream.insert(index, document)`

把 *document* 插入 *index* 位置。

### `DocumentStream.remove(index)`

移除并返回 *index* 处的 `Document`。

### `DocumentStream.dump(stream=None, *, config=None, explicit_start=None, explicit_end=None)`

输出整个流。

- **stream** —— 可写流,或 `None` 以返回文本。
- **config** —— (`IndentConfig | None`)针对被修改文档的输出覆盖。
- **explicit_start** —— (`bool | None`)控制起始 `---` 标记。`None`(默认)保留每个文档自身的标记,因此未经修改的流会精确回放源文本;`True` 补上缺失的标记,`False` 去掉流的起始标记。
- **explicit_end** —— (`bool | None`)以相同语义控制结尾 `...` 标记;省略时每个文档保留自己的标记。

未经修改的流会精确回放源文本。
