# CLI 与配置

## 安装

需要 Python 3.11 或更新版本。运行时不需要第三方包；开发依赖仅包含 pytest。

```bash
python -m venv .venv
```

PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活环境，macOS / Linux 使用 `source .venv/bin/activate`。随后安装并查看命令帮助：

```bash
python -m pip install -e ".[dev]"
python -m trace_agent --help
```

安装后也可使用 `trace-agent` 命令。内置知识库位于已安装包的 `data/knowledge/` 中，不依赖当前工作目录。

## 命令

| 命令 | 作用 | 默认输出 |
| --- | --- | --- |
| `demo` | 运行内置任务，在一次工具提交后暂停，再关闭、重开数据库并恢复 | `out/demo/` |
| `run TASK` | 创建任务并执行 | 数据库 `out/runs.db`，报告 `out/run/` |
| `resume RUN_ID` | 使用已有数据库继续同一个 run | `out/resumed/` |
| `inspect RUN_ID` | 仅导出已有 run，不执行工具或请求模型 | `out/inspect/` |
| `evaluate` | 执行固定工程回归案例，不调用模型 API | `out/evaluation/` |

各命令支持 `--help` 查看参数。所有路径均相对于当前工作目录解析，`--root` 未指定时使用包内知识库。

### 创建与恢复

```bash
python -m trace_agent run "缓存故障的根因和修复方式是什么？" --db out/session.db --out out/first --stop-after 1
python -m trace_agent resume RUN_ID --db out/session.db --out out/resumed
python -m trace_agent inspect RUN_ID --db out/session.db --out out/inspection
```

第一条命令输出 `run_id`、`status` 和报告路径，用实际 ID 替换后两条命令中的 `RUN_ID`。`--stop-after` 统计本次调用中已提交的工具结果，不包含 planner 决策；暂停时该工具的结果已经持久化。

`resume` 必须指向同一个数据库。恢复继续使用创建 run 时保存的知识库目录、provider 与预算；已有终态 `completed / failed / budget_exceeded` 直接返回，不重新执行。需要调整预算或修正终态任务时，创建新的 run。

### 执行预算

预算在 `run` 时设置，并随检查点持久化：

| 参数 | 默认值 | 允许范围 | 计数方式 |
| --- | ---: | --- | --- |
| `--max-steps` | 12 | 1–100 | 通过验证的 planner 动作；最终回答也计一次 |
| `--max-attempts` | 20 | 1–200 | 工具执行总尝试次数，包含失败调用 |
| `--max-retries` | 2 | 0–5 | 每个工具动作或 planner 决策允许的额外重试次数 |

```bash
python -m trace_agent run "cache" --max-steps 8 --max-attempts 10 --max-retries 1
```

每次工具尝试在执行前保存，因此进程在真正调用工具前退出也可能消耗一次尝试。重启不会重置预算。瞬时异常按 50 ms 起始的指数退避重试；参数、权限和永久性错误直接终止。更完整的崩溃窗口见 [事务边界](design.md#sqlite-事务边界)。

## 知识库输入

```bash
python -m trace_agent run "发布前要检查哪些指标？" --root ./my-markdown
```

输入目录需已存在。工具只读取 UTF-8 `.md` 文件：

- `search` 最多扫描 500 篇 Markdown 文档，每篇不超过 256 KiB；返回 1–8 个候选，默认 3 个。
- `read` 接收相对目录的正斜杠路径，行号从 1 开始；每次最多 120 行、12000 字符，默认 80 行。
- 路径解析后仍需位于知识库根目录；绝对路径、`..`、反斜杠和盘符被拒绝。
- `calculator` 仅支持受限的字面量算术，不接受名称、函数、属性访问或代码执行。

默认离线策略只适合可由词项重合定位的查询。知识库内容变更后，恢复时会读到新文件；当前版本没有快照或内容版本锁定。需要可复现执行时，使用单独目录固定知识库版本。

## Chat provider

只有 `run --provider chat` 会调用模型。配置通过进程环境变量提供：

| 环境变量 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `TRACE_AGENT_API_KEY` | 是 | 无 | 服务认证凭据，不写入 SQLite 或报告 |
| `TRACE_AGENT_MODEL` | 是 | 无 | 支持工具调用的模型标识 |
| `TRACE_AGENT_BASE_URL` | 否 | `https://api.openai.com/v1` | 客户端追加 `/chat/completions` |

PowerShell：

```powershell
$env:TRACE_AGENT_API_KEY = "your-key"
$env:TRACE_AGENT_MODEL = "your-tool-capable-model"
$env:TRACE_AGENT_BASE_URL = "https://api.openai.com/v1"
python -m trace_agent run "缓存故障的根因是什么？" --provider chat
```

Bash：

```bash
export TRACE_AGENT_API_KEY="your-key"
export TRACE_AGENT_MODEL="your-tool-capable-model"
export TRACE_AGENT_BASE_URL="https://api.openai.com/v1"
python -m trace_agent run "缓存故障的根因是什么？" --provider chat
```

服务需支持 Chat Completions 的 `tools` 与 `parallel_tool_calls=false`；运行时每次仅接受一个工具动作。客户端限制请求体为 64000 字节、响应体为 1000000 字节，单次请求超时 30 秒。HTTP 408、429、500、502、503、504 和连接错误可重试，其他 HTTP 错误终止任务。HTTP 重定向被拒绝，base URL 仅允许 HTTPS 或 loopback HTTP。

Chat provider 会发送任务以及已读取的工具结果。凭据需在恢复时仍可用；配置不会随状态保存。当前提交的评测使用离线策略，在线路径仅有 mock 合约测试。

## 输出与排障

每次执行或检查生成：

| 文件 | 内容 |
| --- | --- |
| `index.html` | 单文件离线报告；任务、状态、答案和可展开事件 |
| `trace.json` | 结构化 checkpoint 与 journal；知识库根目录替换为 `<knowledge-root>` |
| SQLite 数据库 | 本机恢复所需的完整状态、结果账本和事件；保存原始知识库绝对路径 |

`evaluate` 还生成 `evaluation.json`，逐例保存实际观测与断言结果。HTML 文件需下载后用浏览器打开，GitHub 文件页不直接呈现 HTML 报告。

| 情况 | 检查方法 |
| --- | --- |
| `database does not exist` | 确认 `--db` 指向创建 run 时使用的数据库 |
| `unknown run` | 从原命令输出复制 ID，确认没有混用数据库 |
| `budget_exceeded` | 用 `inspect` 查看已消耗步骤和尝试；调整新任务预算 |
| `failed` | 查看报告中的最后事件，区分非法动作、文档错误或重试耗尽 |
| `stale checkpoint` | 停止同时处理同一 run 的其他 worker；当前版本不提供多 worker 调度 |
| 没有找到证据 | 检查知识库路径、文档编码和查询词项；离线检索不处理语义同义改写 |

退出码：`0` 表示任务完成或已按要求暂停，或全部回归案例通过；`1` 表示任务失败、预算耗尽或有回归案例未通过；`2` 表示输入、配置或命令错误。`inspect` 遇到已失败的 run 也会按该 run 的终态返回相应退出码。

报告包含实际任务和文档内容；公开报告之前应检查其中的数据。数据库与 `out/` 默认被 Git 忽略。
