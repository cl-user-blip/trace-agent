# Trace Agent

**一个能解释“失败以后怎么办”的 Agent 工程项目：持久检查点、受限工具、恢复与可观测执行轨迹。**

![项目概览示意图，非界面截图](docs/preview.svg)

默认零 API key、零运行时第三方依赖。离线演示采用明确标注的**规则策略模拟器**；也提供可选的 OpenAI-compatible Chat Completions 工具调用适配器。重点是把计划、权限、重试、工具结果和恢复语义做成可以检查的代码，而不是把离线策略包装成大模型能力。

**适合关注：** Agent runtime、tool calling、状态机、SQLite 事务、故障注入、可复现评测。

## 30 秒体验

Python 3.11+，从仓库目录执行：

```bash
python -m trace_agent demo
python -m trace_agent evaluate
```

打开 `out/demo/index.html` 查看任务、来源引用和逐事件轨迹；打开 `out/evaluation/index.html` 查看故障案例。两个报告均为单文件 HTML，可直接离线打开。

`demo` 真的执行“搜索后暂停 → 关闭数据库连接 → 重开连接 → 从检查点继续”。已有运行的暂停与继续：

```bash
python -m trace_agent run "缓存 cache 故障根因是什么？" --stop-after 1
# 把输出的 run_id 代入下一条命令
python -m trace_agent resume <run_id>
python -m trace_agent inspect <run_id> --out out/inspect
python -m trace_agent run "计算: (128 - 96) / 128 * 100"
```

也可安装后在其他目录运行，内置演示文档随包安装：

```bash
python -m pip install -e ".[dev]"
trace-agent demo --out out/demo
python -m pytest -q
```

## 实现了什么

| 能力 | 具体实现 | 可以检查的证据 |
|---|---|---|
| 显式状态机 | `running / paused / completed / failed / budget_exceeded`，pending action 在执行前持久化 | [runtime.py](trace_agent/runtime.py) |
| durable checkpoint | 工具结果、调用账本、状态和事件在同一个 SQLite 事务中提交 | [store.py](trace_agent/store.py) |
| 恢复与去重 | 已提交结果按 `run_id + call_id` 读取；未提交的只读调用允许重做 | [恢复测试](tests/test_runtime.py) |
| 工具权限 | 固定 allowlist、参数类型与数量限制、Markdown 根目录约束、符号链接解析 | [tools.py](trace_agent/tools.py) |
| 算术计算 | AST 节点白名单与数值边界，不使用 `eval`、shell 或代码解释器 | [工具测试](tests/test_tools.py) |
| 有界执行 | 决策次数、工具总尝试次数、每步重试次数独立限制 | [评测结果](artifacts/evaluation/evaluation.json) |
| 可观测性 | journal 中保留计划、调用、重试、暂停与完成事件；HTML 可展开检查 | [演示报告](artifacts/demo/index.html) |
| 可选真实模型路径 | 串行 tool calling、环境变量凭据、HTTPS、禁止重定向、响应结构验证 | [planners.py](trace_agent/planners.py) |

内置 `search` 是中英文 token overlap 基线，离线策略是“搜索 → 读前两篇 → 按词项重合摘录来源行”。它没有语义推理、重排序模型或长期记忆。工程问题与检索算法的复杂度在这里有意分开，便于面试时逐层讲清。

## 本地实测

2026-11-24，Python 3.14.6，Windows；运行上面的测试与评测命令得到：

| 验证 | 结果 |
|---|---:|
| pytest | **55 passed，1 skipped** |
| 固定工程回归案例 | **11 / 11** |
| 真实模型 API 调用 | **0** |
| 默认 demo 的工具调用 | **3**：search、read、read |
| 默认 demo 的决策次数 | **4**：3 次工具决策 + 1 次结束 |

唯一跳过的测试需要 Windows 创建符号链接权限。本地附带 Python 3.11/3.12/3.13 的 CI 模板；当前发布版本未上传 workflow，未声明远程 CI 结果。可在启用 GitHub Actions 后自行添加该模板。

11 个案例分别覆盖带引用回答、阈值证据、算术、未知问题拒答、连接重开后的恢复、瞬时故障、重试耗尽、工具白名单、路径穿越、决策预算和伪造引用。[完整结果 JSON](artifacts/evaluation/evaluation.json) 与 [演示 trace JSON](artifacts/demo/trace.json) 均来自实际运行。

**这不是通用智能基准。** 4 篇原创虚构文档和固定案例只能证明这些实现路径满足断言；不能证明真实 LLM 的任务成功率、抗提示注入能力或线上性能。在线适配器只有 mock 合约测试，本次没有用真实 key 调用。

## 替换为自己的知识库

```bash
python -m trace_agent run "发布前检查什么？" --root ./my-markdown
python -m trace_agent run "cache" --max-steps 8 --max-attempts 10 --max-retries 1
```

输入为 UTF-8 `.md` 文件，单文件最多 256 KiB，最多扫描 500 篇；每次读取最多 120 行和 12000 字符。`read` 的引用采用 `[relative/path.md:L5]`，行号从 1 开始。最终回答中出现的引用必须对应本轮实际读过的行，**这个检查只能验证引用来源，不能自动验证主张是否被该行支持**。

## 可选：连接真实模型

仅在显式选择 `--provider chat` 时才会请求 API。模型名由使用者设置，不在代码里绑定特定型号。

```powershell
$env:TRACE_AGENT_API_KEY = "your-key"
$env:TRACE_AGENT_MODEL = "your-tool-capable-model"
$env:TRACE_AGENT_BASE_URL = "https://api.openai.com/v1"
python -m trace_agent run "缓存故障的根因和修复方式是什么？" --provider chat
```

Bash 可用 `export TRACE_AGENT_API_KEY=...` 等价设置。该路径会把任务和工具读取到的文档内容发往指定服务；API key 不写入状态或报告。支持 HTTPS，以及本地开发所需的 loopback HTTP。默认拒绝 HTTP 重定向，避免认证头被转发。兼容端点需支持 `/chat/completions`、`tools` 和 `parallel_tool_calls=false`。每次请求超时 30 秒；预算控制次数，不控制美元成本。重试费用由服务提供方计费规则决定。

## 面试时值得讲清的取舍

1. 为什么结果、journal 和 checkpoint 需要原子提交？提交前后各崩溃会发生什么？
2. 为什么本地去重账本仍不能保证外部支付/发信 exactly-once？
3. 哪些异常能重试，为什么权限错误不重试？全局预算与单步重试怎么交互？
4. 为什么一个合规的引用仍可能不支持答案？下一步如何做主张级评测？
5. 单 worker 状态机如何演进到有租约、调度和外部幂等键的多 worker 系统？

[设计与恢复语义](docs/design.md) · [面试讲解与追问](docs/interview.md)

项目定位是可运行的个人工程练习，没有生产流量、客户部署或真实业务收益声明。所有 fixture 与示例业务数值均为原创虚构数据。MIT License。

## English overview

A dependency-free, inspectable agent runtime with SQLite checkpoints, an atomic result journal, read-only tools, bounded retries, provenance checks, failure injection and standalone HTML traces. The default planner is a deterministic offline simulator. A real Chat Completions adapter is opt-in; live-model performance is not claimed.

