package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
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

func performJSONRequest(r *gin.Engine, method, path string, body interface{}) *httptest.ResponseRecorder {
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

func TestHealthCheck_ReturnsHealthy(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/health", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestClearCache_EmptiesCache(t *testing.T) {
	h := NewHandler()
	// seed cache
	key := h.generateCacheKey("parse", "data")
	h.setCache(key, map[string]string{"ok": "true"}, time.Minute)

	assert.NotEmpty(t, h.cache)

	r := setupRouter(h)
	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/cache/clear", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Empty(t, h.cache)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "Cache cleared successfully", resp["message"])
}

func TestParseFile_BadRequest_InvalidJSON(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	req := httptest.NewRequest("POST", "/parse", bytes.NewBufferString("{"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	msg, _ := resp["error"].(string)
	if !(strings.Contains(msg, "invalid character") || strings.Contains(msg, "unexpected EOF") || strings.Contains(msg, "EOF")) {
		t.Fatalf("expected error message to indicate invalid JSON, got: %v", resp["error"])
	}
}

func TestParseFile_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Missing both content and path
	w := performJSONRequest(r, "POST", "/parse", map[string]string{})
	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Contains(t, resp["error"], "Content")
}

func TestParseFile_CacheHit(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	content := "line1\nline2"
	path := "file.txt"
	cacheKey := h.generateCacheKey("parse", content+path)
	expected := map[string]interface{}{"cached": true, "value": 123}
	h.setCache(cacheKey, expected, time.Minute)

	w := performJSONRequest(r, "POST", "/parse", map[string]string{
		"content": content,
		"path":    path,
	})
	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "true", w.Header().Get("X-Cache-Hit"))

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, expected["cached"], resp["cached"])
	assert.EqualValues(t, expected["value"], resp["value"])
}

func TestParseFile_Success_CacheMiss(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(r, "POST", "/parse", map[string]string{
		"content": "a\nb\nc",
		"path":    "demo.txt",
	})

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "false", w.Header().Get("X-Cache-Hit"))
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
}

func TestAnalyzeDiff_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(r, "POST", "/diff", map[string]string{})
	assert.Equal(t, http.StatusBadRequest, w.Code)

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Contains(t, resp["error"], "OldContent")
}

func TestAnalyzeDiff_Success(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(r, "POST", "/diff", map[string]string{
		"old_content": "a\nb\nc",
		"new_content": "b\nc\nd",
	})
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestCalculateMetrics_BadRequest_MissingContent(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(r, "POST", "/metrics", map[string]string{})
	assert.Equal(t, http.StatusBadRequest, w.Code)

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Contains(t, resp["error"], "Content")
}

func TestCalculateMetrics_CacheHit(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	content := "line1\n// comment\n"
	cacheKey := h.generateCacheKey("metrics", content)
	expected := map[string]interface{}{"cached": "metrics", "ok": true}
	h.setCache(cacheKey, expected, time.Minute)

	w := performJSONRequest(r, "POST", "/metrics", map[string]string{
		"content": content,
	})
	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "true", w.Header().Get("X-Cache-Hit"))

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "metrics", resp["cached"])
	assert.Equal(t, true, resp["ok"])
}

func TestCalculateMetrics_Success_CacheMiss(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := performJSONRequest(r, "POST", "/metrics", map[string]string{
		"content": "x\ny\nz",
	})
	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "false", w.Header().Get("X-Cache-Hit"))
}

func TestCache_SetGet_AndExpiry(t *testing.T) {
	h := NewHandler()
	key := h.generateCacheKey("parse", "payload")
	value := map[string]string{"v": "1"}

	h.setCache(key, value, 10*time.Millisecond)
	got, ok := h.getFromCache(key)
	assert.True(t, ok)
	assert.Equal(t, value, got)

	// Expire
	time.Sleep(20 * time.Millisecond)
	got2, ok2 := h.getFromCache(key)
	assert.False(t, ok2)
	assert.Nil(t, got2)
}

func TestGenerateCacheKey_DeterministicAndUnique(t *testing.T) {
	h := NewHandler()
	k1 := h.generateCacheKey("metrics", "abc")
	k2 := h.generateCacheKey("metrics", "abc")
	k3 := h.generateCacheKey("metrics", "abcd")
	k4 := h.generateCacheKey("parse", "abc")

	assert.Equal(t, k1, k2)
	assert.NotEqual(t, k1, k3)
	assert.NotEqual(t, k1, k4)
	assert.GreaterOrEqual(t, len(k1), len("metrics_")+64)
}

func TestCache_ConcurrencySafety(t *testing.T) {
	h := NewHandler()
	key := h.generateCacheKey("parse", "concurrent")
	value := map[string]int{"a": 1}

	var wg sync.WaitGroup
	// Multiple writers
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			h.setCache(key, map[string]int{"a": i}, time.Second)
		}(i)
	}
	// Multiple readers
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = h.getFromCache(key)
		}()
	}
	wg.Wait()

	got, ok := h.getFromCache(key)
	assert.True(t, ok)
	assert.IsType(t, value, got)
}
