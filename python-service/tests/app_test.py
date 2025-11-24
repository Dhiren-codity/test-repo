import hashlib
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request

from src.code_reviewer import CodeReviewer


class FlexibleFlask(Flask):
    # Allow adding routes after first request (useful for tests that register routes mid-suite)
    def _check_setup_finished(self, f_name: str) -> None:  # type: ignore[override]
        return


app = FlexibleFlask(__name__)

# Simple in-memory cache
cache: Dict[str, Dict[str, Any]] = {}

# Default cache TTL (seconds)
CACHE_TTL = 300

# Reviewer instance (can be monkeypatched in tests)
reviewer = CodeReviewer()


def generate_cache_key(prefix: str, data: str) -> str:
    m = hashlib.sha256()
    m.update(f"{prefix}:{data}".encode("utf-8"))
    return m.hexdigest()


def cached(prefix: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            payload = request.get_json(silent=True) or {}
            content = payload.get("content")

            # If there's no content, bypass caching entirely
            if content is None:
                return func(*args, **kwargs)

            key = generate_cache_key(prefix, str(content))
            now = time.time()
            entry = cache.get(key)

            # Serve from cache if present and not expired
            if entry and entry.get("expires_at", 0) > now:
                data = dict(entry.get("data") or {})
                data["cached"] = True
                return jsonify(data)

            # Compute fresh response
            resp = func(*args, **kwargs)

            # If a tuple (response, status) or (response, status, headers), bypass caching
            if isinstance(resp, tuple):
                return resp

            # For JSON responses with 200 status, add cached=False and store base data without 'cached'
            status = getattr(resp, "status_code", None)
            if hasattr(resp, "get_json") and status == 200:
                base_data = resp.get_json(silent=True) or {}
                # Store without the cached flag
                cache[key] = {"data": base_data, "expires_at": now + CACHE_TTL}
                out = dict(base_data)
                out["cached"] = False
                return jsonify(out)

            # Non-JSON or non-200 responses: return as-is (don't cache)
            return resp

        return wrapper

    return decorator


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "healthy", "service": "python-reviewer"})


@app.post("/review")
@cached("review")
def review_code() -> Any:
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if content is None:
        return jsonify({"error": "Missing 'content' field"}), 400

    language = data.get("language", "python")
    res = reviewer.review_code(content, language)
    # Convert review result into JSON-serializable dict
    issues_list = []
    for it in getattr(res, "issues", []) or []:
        issues_list.append(
            {
                "severity": getattr(it, "severity", None),
                "line": getattr(it, "line", None),
                "message": getattr(it, "message", None),
                "suggestion": getattr(it, "suggestion", None),
            }
        )
    out = {
        "score": getattr(res, "score", None),
        "issues": issues_list,
        "suggestions": list(getattr(res, "suggestions", []) or []),
        "complexity_score": getattr(res, "complexity_score", None),
    }
    return jsonify(out)


@app.post("/review/function")
def review_function() -> Any:
    data = request.get_json(silent=True) or {}
    code = data.get("function_code")
    if code is None:
        return jsonify({"error": "Missing 'function_code' field"}), 400
    res = reviewer.review_function(code)
    return jsonify(res)


@app.post("/cache/clear")
def cache_clear() -> Any:
    cache.clear()
    return jsonify({"message": "Cache cleared successfully"})


@app.get("/cache/stats")
def cache_stats() -> Any:
    now = time.time()
    total = len(cache)
    active = 0
    expired = 0
    for v in cache.values():
        if v.get("expires_at", 0) > now:
            active += 1
        else:
            expired += 1
    return jsonify(
        {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": expired,
            "cache_ttl": CACHE_TTL,
        }
    )


# src/code_reviewer.py
import ast
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class _ComplexityCounter(ast.NodeVisitor):
    def __init__(self) -> None:
        self.count = 1  # start at 1

    def generic_visit(self, node):  # type: ignore[override]
        super().generic_visit(node)

    def visit_If(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_For(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_While(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_Try(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_With(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node):  # type: ignore[override]
        self.count += 1
        self.generic_visit(node)


def _calc_complexity(code: str) -> float:
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return 1.0
    c = _ComplexityCounter()
    c.visit(tree)
    return float(c.count)


def _detect_issues(content: str) -> List[SimpleNamespace]:
    issues: List[SimpleNamespace] = []

    lines = (content or "").splitlines()
    for idx, line in enumerate(lines, 1):
        # Long line
        if len(line) > 120:
            issues.append(
                SimpleNamespace(
                    severity="low",
                    line=idx,
                    message="Line exceeds 120 characters",
                    suggestion="Consider breaking the line for readability.",
                )
            )
        # TODO markers
        if "TODO" in line or "FIXME" in line:
            issues.append(
                SimpleNamespace(
                    severity="low",
                    line=idx,
                    message="TODO/FIXME found",
                    suggestion="Resolve or remove TODO/FIXME comments.",
                )
            )
        # Hardcoded password/secret
        if re.search(r"(password|passwd|secret)\s*=\s*['\"].+['\"]", line, re.IGNORECASE):
            issues.append(
                SimpleNamespace(
                    severity="high",
                    line=idx,
                    message="Hardcoded secret detected",
                    suggestion="Do not store secrets directly in code. Use environment variables or a secret manager.",
                )
            )
    return issues


def _suggestions_from_issues(issues: List[SimpleNamespace]) -> List[str]:
    suggestions: List[str] = []
    for it in issues:
        if it.suggestion and it.suggestion not in suggestions:
            suggestions.append(it.suggestion)
    if not suggestions:
        suggestions.append("Code looks good overall.")
    return suggestions


class CodeReviewer:
    def review_code(self, content: str, language: Optional[str] = None) -> SimpleNamespace:
        content = content or ""
        issues = _detect_issues(content)
        complexity = _calc_complexity(content)

        # Simple scoring: penalize based on issues and complexity
        score = 100
        for it in issues:
            if it.severity == "high":
                score -= 10
            else:
                score -= 5
        # Penalize mildy for complexity above 10
        if complexity > 10:
            score -= int((complexity - 10) * 2)

        score = max(0, min(100, score))

        suggestions = _suggestions_from_issues(issues)

        return SimpleNamespace(
            score=score,
            issues=issues,
            suggestions=suggestions,
            complexity_score=float(complexity),
        )

    def review_function(self, function_code: str) -> Dict[str, Any]:
        function_code = function_code or ""
        res: Dict[str, Any] = {"reviewed": True, "length": len(function_code), "status": "ok"}

        # Attempt to parse and count parameters from the first function definition
        try:
            tree = ast.parse(function_code)
            func_defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            if func_defs:
                f = func_defs[0]
                # Count args (positional + keyword-only + pos-only); exclude *args/**kwargs
                count = len(getattr(f.args, "posonlyargs", [])) + len(f.args.args) + len(f.args.kwonlyargs)
                res["param_count"] = count
                if count > 5:
                    res["warning"] = "Function has too many parameters"
        except SyntaxError:
            res["status"] = "error"
            res["warning"] = "Invalid function code"

        return res