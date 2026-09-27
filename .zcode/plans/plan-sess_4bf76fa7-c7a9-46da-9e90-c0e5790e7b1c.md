# YAMLModel pretty 导出：补全默认值 + Field 注释 + 字段排序 + 容器空行

## 目标 API

```python
class AppConfig(YAMLModel):
    debug: bool = False
    server: Server          # 嵌套 YAMLModel
    name: str = "app"

cfg = AppConfig.model_validate_yaml(source)
cfg.model_dump(pretty=True)                  # → Document（重排后的全新文档）
cfg.model_dump_yaml(pretty=True)             # → str
cfg.model_dump_yaml(pretty=True, stream=f)   # 写流
# YAMLSettings 继承同一 mixin，model_dump(pretty=True) / model_dump_yaml(pretty=True) 直接可用
```

`pretty=False`（默认）行为完全不变，现有 499 个测试（含全部逐字节 round-trip 断言）不动。

## pretty 语义

对文档做四类变换，**始终生成全新 Document**（不复用锚点文档，因为重排在补丁发射器下不生效，见下）：

1. **按模型声明顺序重排**：顶层映射按 `cls.model_fields` 顺序输出；嵌套模型字段按各自模型递归重排（含序列内的模型项）；普通 dict 字段值保持现有顺序。模型未声明的额外键（extra='ignore' 的已知键）**追加在模型字段之后**，按源文件相对顺序。
2. **补全未填充字段**：所有声明字段都出现在输出中——源文件缺席的带默认值字段补上当前值（未改动时即默认值）。仅在**没有其他 pydantic kwargs** 时填充。
3. **Field 元数据注释**：`Field(description=...)` 渲染为键上方的注释块（多行 description → 多行注释）。examples/约束暂不渲染（未选择，留作后续扩展）。若锚点中该键已有相同注释行则去重跳过（保证幂等）。
4. **容器空行规则**：所有块级映射层级的相邻条目之间，只要任一侧是**非空容器**（有元素的 dict/list）就插入一个空行；标量↔标量、涉及空容器的相邻对不加空行；序列项之间不加空行（但序列内映射的内部条目遵守本规则）。

示例：

```yaml
# 源文件                        # model_dump_yaml(pretty=True)
name: myapp                    debug: false
server:
  ports: [8080]                server:
                                 host: localhost      # Field(description="监听地址") 补全的缺失字段
                               name: myapp            # "# app config" 注释随 name 键迁移

# app config（注释跟随 name 移动）
```
（实际输出中 server 前后各一个空行，server 内 host 与 ports 之间一个空行。）

### 注释迁移（带锚点时）

- 每个键路径的**上方注释**（含文件头注释，归属首个条目的 before）与**内联注释**从锚点按路径迁移到新文档；上方注释块的首尾空行条目剥掉（结构性空行由第 4 条规则统一负责），块内部空行保留。
- 仅根级**最后一个**条目迁移其 after 注释（文件尾注释）；其余 after 不迁移——条目间注释已由后一条目的 before 覆盖，避免重复。
- 锚点的标量/集合样式**不迁移**（新文档按库默认样式重新输出，需要时自动加引号）。
- 传入其他 pydantic kwargs（include/exclude/mode/by_alias…）时：pretty 仍做排序/注释/空行，但**跳过**填充、额外键和注释迁移（kwargs 精确指定了要 dump 什么）。

### 幂等性

`pretty(pretty(src)) == pretty(src)`：注释去重 + 空行规则重算 + 已填充字段已存在，保证第二次运行输出不变（写成测试）。

## 实现要点（全部在 Python 层，无 Rust 改动）

可行性结论（已探明）：无键重排 API 且补丁发射器会静默忽略纯重排，因此 pretty 必须走全新文档；`Document.new` 文档 dump 恒走 `_emit_new` → `_render_mapping` 按 dict 插入序输出，注释/空行 API（`_set_comment`，`""` 条目渲染为空行）在新文档上完整可用。

改动 `src/pythonizeyaml/pydantic.py`：

1. `_pretty_mapping(instance, cls, *, fill)`：按 `cls.model_fields` 顺序走实例 getattr，嵌套 BaseModel 递归（`type(value)`），dict/list/tuple 递归元素，产出有序 plain 树。`fill=True` 即"每个字段都出现"（正好实现补全）。叶子值直接用 getattr 结果——与现有变更回写路径一致。
2. `_pretty_from_values(values, cls, *, fill=False)`：kwargs 路径，对 `super().model_dump(**kwargs)` 的 plain 值排序；嵌套模型经 `_model_class_of(field.annotation)`（处理 `Optional[Model]`/`X | Y`，`typing.get_origin/get_args`，解析不出则原样拷贝）。
3. `_build_pretty_document(root, cls, anchor)`：`Document.new(root, config=anchor._config if anchor else None)`，然后一个递归 walker 按路径 `_set_comment`：组装 `before = ([""] if 空行 else []) + description 注释 + 迁移注释`、迁移 inline、根级末条目 after。空行判定基于值树（len>0 的 dict/list）。用路径制 API 而非 `node.comments`，规避 None/True/False 值无包装对象的坑。
4. `model_dump(self, *, pretty: bool = False, **kwargs)`：拦截 pretty（不转发给 pydantic）；顺带修正现状——`super().model_dump(**kwargs)` 目前在锚点路径也被无条件计算（pydantic.py:262），改为按需计算。四条路径：
   - 非 pretty：现有逻辑不变（kwargs/无锚 → `Document.new`；否则 `_sync_mapping` 原地同步）。
   - pretty + 其他 kwargs：`_pretty_from_values(fill=False)` → `_build_pretty_document(anchor=None)`。
   - pretty 无 kwargs：`_pretty_mapping(fill=True)` + 锚点额外键追加 → `_build_pretty_document(anchor=anchor)`（迁移/去重用它）。
5. `model_dump_yaml(*, stream=None, encoding=None, pretty=False)`：透传 pretty。

`pydantic_settings.py` 不改（YAMLSettings 自动继承；锚点即首个 yaml_file 的 Document）。`__init__.py`、pyproject.toml、版本号均不动（仍属未发布的 0.5.0 特性集）。

## 已知边界（文档注明）

- pretty 是**重新生成**：仅注释随键迁移，样式/引号风格/流式集合不保留；逐字节 round-trip 契约只在 `pretty=False` 时成立。
- 排序仅作用于模型映射；pretty 前的源注释若与 description 重复会被去重（这正是幂等的机制）。
- 带其他 pydantic kwargs 时的 pretty 跳过填充/额外键/注释迁移。

## 文件变更

1. `src/pythonizeyaml/pydantic.py`：上述 5 点；模块 docstring 补一句 pretty 语义。
2. `tests/test_pydantic.py` 新增（沿用现有 SOURCE/Minimal 风格，全部精确断言输出文本）：
   - 补全缺失默认字段（含字段位置按声明序）；声明序重排；
   - description 注释（含多行）+ 注释随键迁移 + 文件头/尾注释迁移 + 内联注释迁移；
   - 空行规则精确断言（容器↔任意、标量↔标量无空行、空容器不算容器、嵌套层级）；
   - 嵌套模型递归（排序+补全+注释）；额外键追加末尾；
   - 幂等（pretty 两次 == 一次）；无锚点时直接实例化生成模板；
   - pretty + include kwargs 跳过填充；默认路径逐字节不变的守护测试。
3. `tests/test_pydantic_settings.py` 新增 1–2 个：yaml_file + pretty 的重排/补全/注释输出。
4. 文档 en/zh 同步：`docs/api/pydantic.md` + `docs/zh_CN/api/pydantic.md`——`model_dump`/`model_dump_yaml` 小节加 pretty 参数，新增 "Pretty dumps" 小节（四类变换、示例、幂等、边界），往返边界列表补一条。README 不改（参数级细节）。

## 验证

- `poetry run pytest`：全量通过，现有 499 个测试零改动零失败。
- 新测试全部精确文本断言（不做模糊包含断言）。
- `cmd //c "pnpm run docs:build"` 无 SSR 错误（29+ 页）。