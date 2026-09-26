# 参与贡献 pythonizeyaml

感谢你有兴趣为本项目做贡献!本文档介绍项目结构、如何搭建并测试开发环境,以及提交变更时需要包含的内容。

[English](CONTRIBUTING.md) | 简体中文

## 项目结构

- `src/pythonizeyaml/`:Python API、无损往返容器封装、错误类型与配置。
- `rust/src/`:自研 Rust 词法/语法分析器、无损模型、resolver、emitter 与 PyO3 桥接层。
- `tests/`:pytest 用例与 YAML fixtures;格式错误的 fixtures 位于 `tests/fixtures/invalid/`。
- `docs/`:VuePress 文档站;英文页面位于 `docs/`,中文页面位于 `docs/zh_CN/`。
- `.github/workflows/`:测试与 wheel 发布自动化。

## 开发环境搭建

需要 Python 3.10+、Rust 1.83+ 与 Poetry。

```console
poetry install                              # 安装 Python 依赖
cargo test --manifest-path rust/Cargo.toml  # 运行 Rust 单元测试
poetry run maturin develop                  # 构建原生扩展
poetry run pytest                           # 运行 Python 测试
poetry build                                # 构建 Python wheel/sdist
```

修改任何 Rust 代码后都需要重新运行 `poetry run maturin develop`。仅修改
Python 代码时,可编辑安装会自动生效,无需重新构建。

## 文档构建

文档站使用 VuePress 构建,pnpm 版本固定为 12.6.0。

```console
pnpm install --frozen-lockfile  # 安装文档依赖
pnpm docs:build                 # 构建文档站
```

构建产物输出到 `docs/.vuepress/dist`。

## 代码风格

- Python 遵循 PEP 8,Rust 使用标准 `cargo fmt` 格式化。
- Python 使用四空格缩进;函数与模块用 `snake_case`,类型用 `PascalCase`,
  常量用 `UPPER_SNAKE_CASE`。
- 保持公开 Python API 的类型注解,并在 Rust 中通过 `Result` 传播错误。
- 与周边代码风格保持一致,避免无关的格式改动。

## 测试规范

- Python 行为用 pytest 覆盖,解析器内部用 Rust 单元测试覆盖。
- 测试文件命名为 `test_<feature>.py`,测试函数命名为 `test_<behavior>`。
- 涉及保真、数值、tag、alias 或变更行为的改动,都应附带针对性的回归测试。
- 往返测试在适用时应断言源文本完全一致。
- 格式错误的 YAML 输入放在 `tests/fixtures/invalid/` 下。
- 文档改动必须中英双语同步:保持 `docs/zh_CN/` 与 `docs/` 一致,
  `README.zh_CN.md` 与 `README.md` 一致。

## 提交问题

提交 bug 报告时,请附上能复现问题的最小 YAML 片段、期望行为、实际行为,
以及你的 Python 版本。往返或格式化问题请同时给出原始文本、修改代码与
dump 输出。

## 提交变更

- 提交标题保持简洁、祈使语气(例如 `fix broken python 3.10` 或
  `docs: fix 404 assets`)。
- Pull request 应描述行为变更、列出已运行的测试命令,并说明兼容性或
  安全性影响。
- 格式化相关的改动请附上改动前后的 YAML 示例。

## 安全与兼容性

- 示例与测试中对不可信输入使用 `safe_load`/`safe_load_all`。
- 不得削弱未知 tag 的拒绝逻辑,也不得直接暴露原生解析器异常。
- 除在相关 issue 或讨论中获得明确批准外,保持已文档化的 PyYAML 兼容
  公开 API 不变。
