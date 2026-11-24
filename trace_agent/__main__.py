from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .evaluation import evaluate
from .report import export_trace
from .runtime import Runtime
from .store import ConflictError, Store

DEFAULT_ROOT = str(Path(__file__).resolve().parent / "data" / "knowledge")


def parser():
    p = argparse.ArgumentParser(description="Inspect a durable read-only Agent runtime. Offline by default.")
    sub = p.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="pause after search, close database, resume and export HTML")
    demo.add_argument("--root", default=DEFAULT_ROOT)
    demo.add_argument("--out", default="out/demo")
    run = sub.add_parser("run", help="start a new task")
    run.add_argument("task")
    run.add_argument("--root", default=DEFAULT_ROOT)
    run.add_argument("--db", default="out/runs.db")
    run.add_argument("--out", default="out/run")
    run.add_argument("--provider", choices=["offline", "chat"], default="offline")
    run.add_argument("--max-steps", type=int, default=12)
    run.add_argument("--max-attempts", type=int, default=20)
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--stop-after", type=int)
    resume = sub.add_parser("resume", help="continue the same run from its durable checkpoint")
    resume.add_argument("run_id")
    resume.add_argument("--db", default="out/runs.db")
    resume.add_argument("--out", default="out/resumed")
    resume.add_argument("--stop-after", type=int)
    inspect = sub.add_parser("inspect", help="export a stored run without executing tools")
    inspect.add_argument("run_id")
    inspect.add_argument("--db", default="out/runs.db")
    inspect.add_argument("--out", default="out/inspect")
    ev = sub.add_parser("evaluate", help="run original-fixture regression suite (no API calls)")
    ev.add_argument("--root", default=DEFAULT_ROOT)
    ev.add_argument("--out", default="out/evaluation")
    return p


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            report = evaluate(Path(args.root), args.out)
            print(json.dumps({"passed": report["passed"], "total": report["total"],
                              "report": str(Path(args.out) / "index.html")}, ensure_ascii=False))
            return 0 if report["passed"] == report["total"] else 1
        if args.command == "demo":
            out = Path(args.out)
            store = Store(out / "runs.db")
            try:
                state = store.create("缓存 cache 故障根因是什么，如何修复？", args.root)
                paused = Runtime(store).run(state["id"], stop_after=1)
                export_trace(store, paused, out / "paused")
            finally:
                store.close()
            store = Store(out / "runs.db")
            try:
                state = Runtime(store).run(state["id"])
                path = export_trace(store, state, out)
            finally:
                store.close()
        else:
            if args.command != "run" and not Path(args.db).is_file():
                raise ValueError("database does not exist")
            store = Store(args.db)
            try:
                if args.command == "run":
                    state = store.create(args.task, args.root, args.provider, max_steps=args.max_steps,
                                         max_attempts=args.max_attempts, max_retries=args.max_retries)
                    state = Runtime(store).run(state["id"], stop_after=args.stop_after)
                elif args.command == "resume":
                    state = Runtime(store).run(args.run_id, stop_after=args.stop_after)
                else:
                    state = store.load(args.run_id)
                path = export_trace(store, state, args.out)
            finally:
                store.close()
        print(json.dumps({"run_id": state["id"], "status": state["status"], "report": str(path)}, ensure_ascii=False))
        if state.get("answer"):
            print(state["answer"])
        return 0 if state["status"] in {"completed", "paused"} else 1
    except (ValueError, OSError, KeyError, ConflictError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
