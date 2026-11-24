"""Plan -> checkpoint -> execute -> commit result -> repeat.

All tool execution is outside the SQLite transaction. A crash before result commit
can repeat a call; that is why built-in tools are read-only.
"""
from __future__ import annotations

import re
import time

from .planners import TransientProviderError, make_planner
from .store import Store
from .tools import ToolError, Tools, TransientToolError

TERMINAL = {"completed", "failed", "budget_exceeded"}


def validate_action(action: dict, tools: Tools) -> None:
    if not isinstance(action, dict):
        raise ValueError("planner action must be an object")
    if action.get("type") == "final":
        if set(action) != {"type", "answer"} or not isinstance(action["answer"], str) or not 1 <= len(action["answer"]) <= 8000:
            raise ValueError("invalid final answer")
    elif action.get("type") == "tool":
        if set(action) != {"type", "name", "arguments"} or not isinstance(action["name"], str):
            raise ValueError("invalid tool action")
        tools.validate(action["name"], action["arguments"])
    else:
        raise ValueError("unknown action type")


def validate_citations(answer: str, history: list[dict]) -> None:
    allowed = {row["citation"] for item in history if item["name"] == "read"
               for row in item["result"]["lines"]}
    cited = set(re.findall(r"\[[^\]\n]+:L\d+\]", answer))
    if cited - allowed:
        raise ValueError("answer cites a source line that was never read")


class Runtime:
    def __init__(self, store: Store, *, planner=None, tools=None, backoff: float = .05):
        self.store = store
        self.planner = planner
        self.tools = tools
        self.backoff = backoff

    def fail(self, state, reason, *, budget=False):
        state["status"] = "budget_exceeded" if budget else "failed"
        state["error"] = reason
        return self.store.save(state, state["status"], {"reason": reason})

    def run(self, run_id: str, *, stop_after: int | None = None) -> dict:
        if stop_after is not None and stop_after < 1:
            raise ValueError("stop_after must be positive")
        state = self.store.load(run_id)
        if state["status"] in TERMINAL:
            return state
        tools = self.tools or Tools(state["knowledge_root"])
        planner = self.planner or make_planner(state["provider"])
        if state["status"] == "paused":
            state["status"] = "running"
            state = self.store.save(state, "resumed")
        executed = 0
        while True:
            limits = state["limits"]
            if state["pending"] is None:
                if state["decisions"] >= limits["max_steps"]:
                    return self.fail(state, "decision budget exhausted", budget=True)
                try:
                    action = planner.decide(state)
                    validate_action(action, tools)
                except TransientProviderError:
                    state["planner_failures"] += 1
                    state = self.store.save(state, "provider_retry", {"attempt": state["planner_failures"]})
                    if state["planner_failures"] > limits["max_retries"]:
                        return self.fail(state, "provider retry budget exhausted")
                    time.sleep(self.backoff * 2 ** (state["planner_failures"] - 1))
                    continue
                except (ValueError, TypeError, KeyError):
                    return self.fail(state, "planner returned an invalid or unauthorized action")
                state["planner_failures"] = 0
                state["decisions"] += 1
                if action["type"] == "final":
                    try:
                        validate_citations(action["answer"], state["history"])
                    except ValueError:
                        return self.fail(state, "final answer contains an unobserved citation")
                    state["answer"] = action["answer"]
                    state["status"] = "completed"
                    return self.store.save(state, "completed", {"answer": action["answer"]})
                state["pending"] = {"call_id": f"call_{state['id']}_{state['decisions']}",
                                    "action": action, "attempts": 0}
                state = self.store.save(state, "planned", state["pending"])
            pending = state["pending"]
            cached = self.store.cached(run_id, pending["call_id"])
            if cached is None:
                if state["attempts"] >= limits["max_attempts"]:
                    return self.fail(state, "tool attempt budget exhausted", budget=True)
                if pending["attempts"] >= limits["max_retries"] + 1:
                    return self.fail(state, "tool retry budget exhausted")
                state["attempts"] += 1
                state["pending"]["attempts"] += 1
                state = self.store.save(state, "tool_started", {
                    "call_id": pending["call_id"], "attempt": state["pending"]["attempts"]})
                pending = state["pending"]
                action = pending["action"]
                try:
                    result = tools.invoke(action["name"], action["arguments"])
                except TransientToolError:
                    state = self.store.save(state, "tool_retry", {
                        "call_id": pending["call_id"], "attempt": pending["attempts"]})
                    if pending["attempts"] >= limits["max_retries"] + 1:
                        return self.fail(state, "tool retry budget exhausted")
                    time.sleep(self.backoff * 2 ** (pending["attempts"] - 1))
                    continue
                except (ToolError, OSError, UnicodeError):
                    return self.fail(state, "tool input, permission, or document error")
            else:
                result = cached
            action = pending["action"]
            state["history"].append({"call_id": pending["call_id"], "name": action["name"],
                                     "arguments": action["arguments"], "result": result})
            state["pending"] = None
            state = self.store.save(state, "tool_result", {
                "call_id": pending["call_id"], "name": action["name"], "cached": cached is not None,
                "result": result}, result=(pending["call_id"], result))
            executed += 1
            if stop_after is not None and executed >= stop_after:
                state["status"] = "paused"
                return self.store.save(state, "paused", {"completed_tools_this_invocation": executed})

