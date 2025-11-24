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

func performJSONRequest(t *testing.T, r *gin.Engine, method, path string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		err := json.NewEncoder(&buf).Encode(body)
		if err != nil {
			t.Fatalf("failed to encode body: %v", err)
		}
	}
	req := httptest.NewRequest(method, path, &buf)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(t, r, http.MethodGet, "/health", nil)
	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")

	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name       string
		body       any
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       nil,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing required fields",
			body:       map[string]any{"content": "package main\nfunc main(){}"},
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing both fields",
			body:       map[string]any{},
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performJSONRequest(t, r, http.MethodPost, "/parse", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestParseFile_CacheHit(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	content := "package main\nfunc main(){}"
	path := "main.go"
	cacheKey := h.generateCacheKey("parse", content+path)
	cached := map[string]any{"cached": true, "kind": "parseResult"}

	h.setCache(cacheKey, cached, 5*time.Minute)

	body := map[string]any{
		"content": content,
		"path":    path,
	}
	w := performJSONRequest(t, r, http.MethodPost, "/parse", body)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "true", w.Header().Get("X-Cache-Hit"))

	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, true, resp["cached"])
	assert.Equal(t, "parseResult", resp["kind"])
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name string
		body any
	}{
		{
			name: "missing required fields",
			body: map[string]any{},
		},
		{
			name: "missing new_content",
			body: map[string]any{"old_content": "a"},
		},
		{
			name: "missing old_content",
			body: map[string]any{"new_content": "b"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performJSONRequest(t, r, http.MethodPost, "/diff", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr)
		})
	}
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(t, r, http.MethodPost, "/metrics", map[string]any{})
	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	_, hasErr := resp["error"]
	assert.True(t, hasErr)
}

func TestCalculateMetrics_CacheHit(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	content := "package main\nfunc main(){}"
	cacheKey := h.generateCacheKey("metrics", content)
	cached := map[string]any{"cached": true, "kind": "metricsResult"}

	h.setCache(cacheKey, cached, 5*time.Minute)

	body := map[string]any{
		"content": content,
	}
	w := performJSONRequest(t, r, http.MethodPost, "/metrics", body)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "true", w.Header().Get("X-Cache-Hit"))

	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, true, resp["cached"])
	assert.Equal(t, "metricsResult", resp["kind"])
}

func TestClearCache_RemovesEntries(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Preload cache entries
	parseKey := h.generateCacheKey("parse", "abc"+"x.go")
	metricsKey := h.generateCacheKey("metrics", "abc")
	h.setCache(parseKey, map[string]any{"v": 1}, 5*time.Minute)
	h.setCache(metricsKey, map[string]any{"v": 2}, 5*time.Minute)

	// Sanity: entries exist
	if _, ok := h.getFromCache(parseKey); !ok {
		t.Fatalf("expected parseKey preloaded")
	}
	if _, ok := h.getFromCache(metricsKey); !ok {
		t.Fatalf("expected metricsKey preloaded")
	}

	// Clear via HTTP
	w := performJSONRequest(t, r, http.MethodPost, "/cache/clear", nil)
	assert.Equal(t, http.StatusOK, w.Code)

	// Ensure cleared
	if _, ok := h.getFromCache(parseKey); ok {
		t.Fatalf("expected parseKey to be cleared")
	}
	if _, ok := h.getFromCache(metricsKey); ok {
		t.Fatalf("expected metricsKey to be cleared")
	}
}

func TestCacheExpiryHelpers(t *testing.T) {
	h := NewHandler()
	key := "k1"
	val := map[string]any{"a": 1}
	h.setCache(key, val, -1*time.Second) // expired

	if _, ok := h.getFromCache(key); ok {
		t.Fatalf("expected expired cache miss")
	}

	h.setCache(key, val, 1*time.Hour)
	got, ok := h.getFromCache(key)
	assert.True(t, ok)
	assert.Equal(t, val, got)
}

func TestGenerateCacheKey_StableAndPrefixed(t *testing.T) {
	h := NewHandler()
	k1 := h.generateCacheKey("parse", "data")
	k2 := h.generateCacheKey("parse", "data")
	k3 := h.generateCacheKey("metrics", "data")
	assert.Equal(t, k1, k2)
	assert.NotEqual(t, k1, k3)
	assert.Regexp(t, "^parse_", k1)
	assert.Regexp(t, "^metrics_", k3)
}
