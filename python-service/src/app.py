import sys
import os
import hashlib
import time
import threading
from functools import wraps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify  # noqa: E402
from flask_cors import CORS  # noqa: E402
from src.code_reviewer import CodeReviewer  # noqa: E402

app = Flask(__name__)
CORS(app)

reviewer = CodeReviewer()

cache = {}
# The module-level cache is shared by threaded WSGI workers in this process.
cache_lock = threading.Lock()
CACHE_TTL = 300


def generate_cache_key(prefix, data):
    content = f"{prefix}:{data}"
    return hashlib.sha256(content.encode()).hexdigest()


def cached(prefix):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            data = request.get_json()
            content = data.get("content", "") if data else ""
            cache_key = generate_cache_key(prefix, content)

            with cache_lock:
                entry = cache.get(cache_key)
                if entry and time.time() < entry["expires_at"]:
                    return jsonify({**entry["data"], "cached": True})

                if entry:
                    cache.pop(cache_key, None)

                result = f(*args, **kwargs)
                if isinstance(result, tuple):
                    return result
                response_data = result.get_json()

                cache[cache_key] = {
                    "data": response_data,
                    "expires_at": time.time() + CACHE_TTL,
                }

            return jsonify({**response_data, "cached": False})

        return wrapper

    return decorator


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "python-reviewer"})


@app.route("/review", methods=["POST"])
@cached("review")
def review_code():
    data = request.get_json()

    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    content = data.get("content", "")
    language = data.get("language", "python")

    result = reviewer.review_code(content, language)

    return jsonify(
        {
            "score": result.score,
            "issues": [
                {
                    "severity": issue.severity,
                    "line": issue.line,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                }
                for issue in result.issues
            ],
            "suggestions": result.suggestions,
            "complexity_score": result.complexity_score,
        }
    )


@app.route("/review/function", methods=["POST"])
def review_function():
    data = request.get_json()

    if not data or "function_code" not in data:
        return jsonify({"error": "Missing 'function_code' field"}), 400

    function_code = data.get("function_code", "")
    result = reviewer.review_function(function_code)

    return jsonify(result)


@app.route("/cache/clear", methods=["POST"])
def clear_cache():
    with cache_lock:
        cache.clear()
    return jsonify({"message": "Cache cleared successfully"})


@app.route("/cache/stats", methods=["GET"])
def cache_stats():
    current_time = time.time()
    with cache_lock:
        total_entries = len(cache)
        active_entries = sum(1 for entry in cache.values() if current_time < entry["expires_at"])
        expired_entries = total_entries - active_entries

    return jsonify(
        {
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": expired_entries,
            "cache_ttl": CACHE_TTL,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=False)
