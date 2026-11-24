"""Only read-only tools are built in. The registry is the authorization boundary."""
from __future__ import annotations

import ast
import math
import operator
import re
from pathlib import Path


class ToolError(ValueError):
    pass


class SecurityError(ToolError):
    pass


class TransientToolError(RuntimeError):
    """Only this explicit category is eligible for a bounded retry."""


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return words


SCHEMAS = {
    "search": {"query": str, "limit": int},
    "read": {"path": str, "start": int, "limit": int},
    "calculator": {"expression": str},
}
REQUIRED = {"search": {"query"}, "read": {"path"}, "calculator": {"expression"}}


class Tools:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ToolError("knowledge root must be a directory")

    def validate(self, name: str, arguments: dict) -> None:
        if name not in SCHEMAS:
            raise SecurityError(f"tool is not allowed: {name}")
        if not isinstance(arguments, dict):
            raise ToolError("arguments must be an object")
        if not REQUIRED[name] <= arguments.keys() or arguments.keys() - SCHEMAS[name].keys():
            raise ToolError("missing or unexpected tool arguments")
        for key, value in arguments.items():
            if type(value) is not SCHEMAS[name][key]:
                raise ToolError(f"invalid type for {key}")

    def invoke(self, name: str, arguments: dict) -> dict:
        self.validate(name, arguments)
        return getattr(self, name)(**arguments)

    def confined(self, path: str) -> Path:
        supplied = Path(path)
        if supplied.is_absolute() or ".." in supplied.parts or "\\" in path or ":" in path:
            raise SecurityError("only relative forward-slash Markdown paths are allowed")
        resolved = (self.root / supplied).resolve(strict=True)
        if not resolved.is_relative_to(self.root) or resolved.suffix.lower() != ".md":
            raise SecurityError("path escapes knowledge root or is not Markdown")
        if not resolved.is_file() or resolved.stat().st_size > 262144:
            raise ToolError("file is not a small text document")
        return resolved

    def read(self, path: str, start: int = 1, limit: int = 80) -> dict:
        if not 1 <= start or not 1 <= limit <= 120:
            raise ToolError("start >= 1 and 1 <= limit <= 120 required")
        full = self.confined(path)
        lines = full.read_text(encoding="utf-8").splitlines()
        rows = [{"line": i + 1, "text": line, "citation": f"[{path}:L{i + 1}]"}
                for i, line in enumerate(lines) if start <= i + 1 < start + limit]
        if sum(len(row["text"]) for row in rows) > 12000:
            raise ToolError("requested text exceeds 12000 character limit")
        return {"path": path, "lines": rows, "total_lines": len(lines)}

    def search(self, query: str, limit: int = 3) -> dict:
        if not 1 <= limit <= 8 or not 1 <= len(query) <= 1000:
            raise ToolError("search query or limit out of bounds")
        query_terms = tokens(query)
        hits = []
        paths = sorted(self.root.rglob("*.md"))
        if len(paths) > 500:
            raise ToolError("demo search is limited to 500 Markdown files")
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            full = self.confined(relative)  # resolves symlinks before any read
            content = full.read_text(encoding="utf-8")
            overlap = query_terms & tokens(content)
            if overlap:
                hits.append({"path": relative, "score": len(overlap),
                             "matched_terms": sorted(overlap)})
        hits.sort(key=lambda h: (-h["score"], h["path"]))
        return {"hits": hits[:limit], "query": query, "method": "token-overlap baseline"}

    def calculator(self, expression: str) -> dict:
        if len(expression) > 128:
            raise ToolError("expression too long")
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError) as exc:
            raise ToolError("invalid arithmetic expression") from exc
        if len(list(ast.walk(tree))) > 40:
            raise ToolError("expression too complex")
        binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}

        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = node.value
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp) and type(node.op) in binary:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 8:
                    raise ToolError("power exceeds limit")
                value = binary[type(node.op)](left, right)
            else:
                raise SecurityError("only numeric literals and arithmetic operators are allowed")
            if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e12:
                raise ToolError("numeric result out of bounds")
            return value

        try:
            result = visit(tree.body)
        except (ZeroDivisionError, OverflowError, TypeError) as exc:
            raise ToolError("undefined or out-of-bounds arithmetic") from exc
        return {"expression": expression, "value": result}

