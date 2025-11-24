package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func setupRouter(h *Handler) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.GET("/health", h.HealthCheck)
	r.POST("/cache/clear", h.ClearCache)
	return r
}

func doJSONRequest(t *testing.T, r http.Handler, method, path string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		_ = json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, path, &buf)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck_OK(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	// Missing required field "path"
	body := map[string]string{"content": "package main"}
	w := doJSONRequest(t, router, http.MethodPost, "/parse", body)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "Path")
}

func TestParseFile_CacheBehavior(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	reqBody := map[string]string{
		"content": "package main\nfunc main(){}",
		"path":    "main.go",
	}

	// First request - expect cache miss
	w1 := doJSONRequest(t, router, http.MethodPost, "/parse", reqBody)
	assert.Equal(t, http.StatusOK, w1.Code)
	assert.Equal(t, "false", w1.Header().Get("X-Cache-Hit"))
	firstResp := w1.Body.Bytes()

	// Second request (same body) - expect cache hit
	w2 := doJSONRequest(t, router, http.MethodPost, "/parse", reqBody)
	assert.Equal(t, http.StatusOK, w2.Code)
	assert.Equal(t, "true", w2.Header().Get("X-Cache-Hit"))
	assert.Equal(t, firstResp, w2.Body.Bytes())
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	// Missing required field "new_content"
	body := map[string]string{"old_content": "a"}
	w := doJSONRequest(t, router, http.MethodPost, "/diff", body)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "NewContent")
}

func TestAnalyzeDiff_OK(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	body := map[string]string{
		"old_content": "package main\nfunc a(){}",
		"new_content": "package main\nfunc a(){}\nfunc b(){}",
	}
	w := doJSONRequest(t, router, http.MethodPost, "/diff", body)

	assert.Equal(t, http.StatusOK, w.Code)
	// Response shape is parser-defined; just ensure it's JSON
	var resp any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	// Missing required field "content"
	body := map[string]string{}
	w := doJSONRequest(t, router, http.MethodPost, "/metrics", body)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "Content")
}

func TestCalculateMetrics_CacheBehavior(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	body := map[string]string{
		"content": "line1\nline2\nline3",
	}

	// First request - cache miss
	w1 := doJSONRequest(t, router, http.MethodPost, "/metrics", body)
	assert.Equal(t, http.StatusOK, w1.Code)
	assert.Equal(t, "false", w1.Header().Get("X-Cache-Hit"))
	firstResp := w1.Body.Bytes()

	// Second request - cache hit
	w2 := doJSONRequest(t, router, http.MethodPost, "/metrics", body)
	assert.Equal(t, http.StatusOK, w2.Code)
	assert.Equal(t, "true", w2.Header().Get("X-Cache-Hit"))
	assert.Equal(t, firstResp, w2.Body.Bytes())
}

func TestClearCache_EmptiesCache(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	// Warm cache via metrics or parse
	_ = doJSONRequest(t, router, http.MethodPost, "/metrics", map[string]string{"content": "x"})

	h.mu.RLock()
	before := len(h.cache)
	h.mu.RUnlock()
	if before == 0 {
		t.Fatalf("expected cache to be warmed, got %d", before)
	}

	w := doJSONRequest(t, router, http.MethodPost, "/cache/clear", nil)
	assert.Equal(t, http.StatusOK, w.Code)

	h.mu.RLock()
	after := len(h.cache)
	h.mu.RUnlock()
	assert.Equal(t, 0, after)

	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Equal(t, "Cache cleared successfully", resp["message"])
}

func TestCacheExpiry_Internal(t *testing.T) {
	h := NewHandler()
	// set and then expire quickly
	key := h.generateCacheKey("test", "payload")
	h.setCache(key, map[string]string{"x": "y"}, 10*time.Millisecond)

	if _, ok := h.getFromCache(key); !ok {
		t.Fatal("expected cache hit immediately after set")
	}

	time.Sleep(20 * time.Millisecond)

	if _, ok := h.getFromCache(key); ok {
		t.Fatal("expected cache entry to be expired")
	}
}

func TestGenerateCacheKey_Deterministic(t *testing.T) {
	h := NewHandler()
	k1 := h.generateCacheKey("p", "data")
	k2 := h.generateCacheKey("p", "data")
	k3 := h.generateCacheKey("p", "other")

	assert.Equal(t, k1, k2)
	assert.NotEqual(t, k1, k3)
}
