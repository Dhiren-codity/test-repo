from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

try:
    # Local imports; these modules are expected to exist in the project
    from src.cachekit import cache_stats as ck_cache_stats, clear_cache as ck_clear_cache, health_check as ck_health_check
    from src.reviews import review_code as rv_review_code, review_function as rv_review_function
except Exception as e:
    # Provide clearer error during test collection if imports fail
    # Raising the original exception preserves the traceback for debugging
    raise

app = FastAPI(title="Code Review Service")


class CodeRequest(BaseModel):
    code: str


class FunctionRequest(BaseModel):
    code: str
    name: Optional[str] = None


@app.get("/health")
def get_health() -> Dict[str, Any]:
    return ck_health_check()


@app.post("/review/code")
def post_review_code(payload: CodeRequest) -> Dict[str, Any]:
    return rv_review_code(payload.code)


@app.post("/review/function")
def post_review_function(payload: FunctionRequest) -> Dict[str, Any]:
    return rv_review_function(payload.code, payload.name)


@app.get("/cache/stats")
def get_cache_stats() -> Dict[str, Any]:
    return ck_cache_stats()


class CacheClearRequest(BaseModel):
    namespace: Optional[str] = None


@app.post("/cache/clear")
def post_cache_clear(payload: CacheClearRequest) -> Dict[str, Dict[str, int]]:
    if not payload.namespace:
        raise HTTPException(status_code=400, detail="namespace is required")
    result = ck_clear_cache(namespace=payload.namespace)
    # If no matching caches were cleared, return 404 per test expectations
    if not result or payload.namespace not in result:
        raise HTTPException(status_code=404, detail="No matching caches")
    return {"cleared": result}