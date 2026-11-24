"""Atomic state + result ledger + journal, with optimistic concurrency checks."""
from __future__ import annotations

import json
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ConflictError(RuntimeError):
    pass


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
          kind TEXT NOT NULL, time TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS results (
          run_id TEXT NOT NULL REFERENCES runs(id), call_id TEXT NOT NULL,
          result TEXT NOT NULL, PRIMARY KEY (run_id, call_id));
        """)

    def close(self):
        self.connection.close()

    def create(self, task: str, knowledge_root: str, provider: str = "offline", *,
               max_steps: int = 12, max_attempts: int = 20, max_retries: int = 2) -> dict:
        if not task.strip() or len(task) > 2000:
            raise ValueError("task must have 1..2000 characters")
        if not 1 <= max_steps <= 100 or not 1 <= max_attempts <= 200 or not 0 <= max_retries <= 5:
            raise ValueError("budgets out of range")
        state = {"id": uuid.uuid4().hex[:12], "revision": 0, "task": task,
                 "knowledge_root": str(Path(knowledge_root).resolve()), "provider": provider,
                 "status": "running", "history": [], "pending": None, "answer": None,
                 "decisions": 0, "attempts": 0, "planner_failures": 0,
                 "limits": {"max_steps": max_steps, "max_attempts": max_attempts,
                            "max_retries": max_retries}}
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?, ?, ?)",
                                    (state["id"], 0, dumps(state)))
            self._event(state["id"], "created", {"task": task, "provider": provider})
        return state

    def _event(self, run_id, kind, payload):
        self.connection.execute("INSERT INTO events(run_id,kind,time,payload) VALUES(?,?,?,?)",
                                (run_id, kind, datetime.now(timezone.utc).isoformat(), dumps(payload)))

    def save(self, state: dict, kind: str, payload: dict | None = None,
             result: tuple[str, dict] | None = None) -> dict:
        changed = deepcopy(state)
        changed["revision"] += 1
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE runs SET revision=?,state=? WHERE id=? AND revision=?",
                (changed["revision"], dumps(changed), state["id"], state["revision"]))
            if cursor.rowcount != 1:
                raise ConflictError("stale checkpoint: another worker changed this run")
            if result is not None:
                self.connection.execute("INSERT OR IGNORE INTO results VALUES (?,?,?)",
                                        (state["id"], result[0], dumps(result[1])))
            self._event(state["id"], kind, payload or {})
        return changed

    def load(self, run_id: str) -> dict:
        row = self.connection.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return json.loads(row[0])

    def cached(self, run_id: str, call_id: str):
        row = self.connection.execute("SELECT result FROM results WHERE run_id=? AND call_id=?",
                                      (run_id, call_id)).fetchone()
        return None if row is None else json.loads(row[0])

    def events(self, run_id: str) -> list[dict]:
        return [{"seq": row[0], "kind": row[1], "time": row[2], "payload": json.loads(row[3])}
                for row in self.connection.execute(
                    "SELECT seq,kind,time,payload FROM events WHERE run_id=? ORDER BY seq", (run_id,))]

