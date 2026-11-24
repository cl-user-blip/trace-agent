"""Small assertion-based engineering evaluation, not an intelligence benchmark."""
from __future__ import annotations

from pathlib import Path

from .planners import OfflinePlanner, final, tool
from .report import export_eval, export_trace
from .runtime import Runtime
from .store import Store
from .tools import Tools, TransientToolError


class FixedPlanner:
    def __init__(self, action):
        self.action = action

    def decide(self, state):
        return self.action


class FlakyTools(Tools):
    def __init__(self, root, failures=1):
        super().__init__(root)
        self.failures = failures
        self.calls = 0

    def invoke(self, name, arguments):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientToolError("injected transient read failure")
        return super().invoke(name, arguments)


def evaluate(root, out) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / "evaluation.db")
    cases = []

    def run(task, *, planner=None, tools=None, **limits):
        state = store.create(task, str(root), **limits)
        state = Runtime(store, planner=planner, tools=tools, backoff=0).run(state["id"])
        return state

    def case(name, purpose, passed, observed):
        cases.append({"name": name, "purpose": purpose, "passed": bool(passed), "observed": observed})

    try:
        state = run("缓存 cache 故障根因是什么？")
        case("grounded incident", "检索、读取、引用原始证据", state["status"] == "completed" and
             "namespace" in (state["answer"] or "") and "[incident.md:L" in (state["answer"] or ""),
             f"{state['status']}; {len(state['history'])} tools")
        export_trace(store, state, out / "grounded-trace")
        state = run("回滚 rollback 的触发条件是什么？")
        case("rollback evidence", "跨文档搜索后保留精确阈值", "2%" in (state["answer"] or "") and
             "[deployment.md:L" in (state["answer"] or ""), state["status"])
        state = run("计算: (128 - 96) / 128 * 100")
        case("bounded arithmetic", "算术工具得到真实数值", state["history"][0]["result"].get("value") == 25,
             state["history"][0]["result"].get("value"))
        state = run("quasar neutrino spectrometer")
        case("unknown question", "未找到证据时明确拒答", "无法回答" in (state["answer"] or ""), state["status"])

        resumed = store.create("缓存 cache 故障根因是什么？", str(root))
        paused = Runtime(store).run(resumed["id"], stop_after=1)
        already = paused["history"][0]["call_id"]
        store.close()  # close/reopen to demonstrate persistence beyond a connection
        store = Store(out / "evaluation.db")
        resumed = Runtime(store).run(resumed["id"])
        result_events = [e for e in store.events(resumed["id"]) if e["kind"] == "tool_result"
                         and e["payload"]["call_id"] == already]
        case("checkpoint resume", "关闭连接后恢复且不重做已提交调用", paused["status"] == "paused" and
             resumed["status"] == "completed" and len(result_events) == 1,
             f"committed first-call results={len(result_events)}")
        export_trace(store, resumed, out / "resumed-trace")

        flaky = FlakyTools(root)
        state = run("缓存 cache 故障根因是什么？", tools=flaky)
        retries = sum(e["kind"] == "tool_retry" for e in store.events(state["id"]))
        case("transient retry", "只对标记为 transient 的异常重试", state["status"] == "completed" and retries == 1,
             f"retry events={retries}; attempts={state['attempts']}")
        state = run("retry exhaustion", planner=FixedPlanner(tool("search", query="cache")), tools=FlakyTools(root, 10))
        case("bounded retries", "持续故障在三次尝试后停止", state["status"] == "failed" and state["attempts"] == 3,
             f"{state['status']}; attempts={state['attempts']}")
        state = run("forbidden tool", planner=FixedPlanner(tool("shell", command="whoami")))
        case("tool allowlist", "未知工具在执行前被拒绝", state["status"] == "failed" and state["attempts"] == 0,
             f"{state['status']}; attempts={state['attempts']}")
        state = run("path escape", planner=FixedPlanner(tool("read", path="../secret.md")))
        case("path confinement", "路径穿越被拒绝且不重试", state["status"] == "failed" and state["attempts"] == 1,
             f"{state['status']}; attempts={state['attempts']}")
        state = run("endless tool loop", planner=FixedPlanner(tool("search", query="cache")), max_steps=2)
        case("decision budget", "无限计划在预算边界终止", state["status"] == "budget_exceeded" and state["decisions"] == 2,
             f"{state['status']}; decisions={state['decisions']}")
        state = run("fabricated citation", planner=FixedPlanner(final("答案 [secret.md:L99]")))
        case("citation provenance", "拒绝引用未读取的来源行", state["status"] == "failed", state["status"])
        report = {"suite": "original-fixture engineering regression", "provider": "offline-rule-simulator",
                  "live_api_calls": 0, "passed": sum(c["passed"] for c in cases), "total": len(cases), "cases": cases}
        export_eval(report, out)
        return report
    finally:
        store.close()

