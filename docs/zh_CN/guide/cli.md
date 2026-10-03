# 命令行

安装 wheel 时会在库旁边附带一个 `yaml` 命令。它在 shell 中按路径编辑单个 YAML 文件——写脚本、跑 CI,或者只需要改一行时非常顺手:

```console
yaml <file> <get|set|del> <path> [value]
```

```console
$ yaml config.yaml get service.port
8080
$ yaml config.yaml set service.port 9090
$ yaml config.yaml get service.port
9090
```

命令与库使用同一套引擎,因此凡是没有被修改的内容,其注释、缩进和标量风格都会原样保留。

## 1. 路径

路径以点分隔。每一段下降一层映射键;纯数字段表示该位置的序列下标:

```console
yaml config.yaml get service.port          # 映射键
yaml config.yaml get servers.0.host        # `servers` 序列的第一项
```

只包含数字的映射键仍是字符串键:`foo.0` 读取 `foo` 里的 `"0"` 键,而不是序列下标。包含点的键无法用路径表示。每一段都必须非空(`a..b` 会被拒绝)。

## 2. `get`

`get` 以 YAML 形式输出路径处的值。标量输出为一行(`8080`、`true`、`hello world`);集合输出为 YAML 块:

```console
$ yaml config.yaml get servers.0
host: h1
port: 8080
```

路径不存在时以退出码 1 结束,并指出能解析到的最深层段。

## 3. `set` 会自动创建缺失的层级

`set` 在路径处写入值,并自动创建尚不存在的中间映射——是整条链,而不只是叶子:

```console
$ yaml config.yaml set tls.enabled true
$ yaml config.yaml get tls
enabled: true
```

对空文件同样有效:`yaml new.yaml set a.b 1` 会生成一份合法的两行文档。

值参数按 YAML 解析,类型是显式的:

| 参数 | 存储为 |
|---|---|
| `123` | 整数 `123` |
| `true` / `false` | 布尔值 |
| `1.5` | 浮点数 |
| `null` | 空值 |
| `[1, 2, 3]` | 列表 |
| `hello world` | 字符串 `"hello world"` |
| `"'123'"` | 字符串 `"123"`(引号经 shell 剥离后强制为字符串) |

把值用引号包起来可以让 `123`、`true` 这类文本保持为字符串。向序列 `set` 会替换已有项(`servers.0.port 8080`);不会追加或扩展序列。

## 4. `del`

`del` 删除路径处的节点——叶子、整个块值条目,或序列项:

```console
$ yaml config.yaml del service.debug
```

删除某个条目的最后一个子节点后会留下 `key: {}`(序列则是 `key: []`),文件读回来仍是空集合而不是 null。路径不存在时以退出码 1 结束,文件不做任何修改。

## 5. 哪些内容逐字节保持

命令用与库相同的往返引擎加载文件,只对发生变化的片段打补丁:

- 其余位置的注释、空行和格式完全保留;
- 对已有标量的 `set` 只重写该标量;
- 新建的链以规范形式追加(默认两空格缩进)——它没有需要保留的源布局。

只接受单文档文件;多文档文件会报错退出,而不是悄悄丢弃其余文档。

## 6. 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 成功(`get` 输出值) |
| `1` | 运行失败:文件不存在、路径不存在、解析错误、多文档输入 |
| `2` | 用法错误:未知命令、路径格式错误、参数数量不对 |

`yaml --help` 输出用法摘要。
