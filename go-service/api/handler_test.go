package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func setupRouter(h *Handler) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)
	return r
}

func TestHealthCheck_OK(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))

	var body map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &body)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", body["status"])
	assert.Equal(t, "go-parser", body["service"])
}

func TestParseFile_BadJSON(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(`{"content":`)) // malformed
	req.Header.Set("Content-Type", "application/json")

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	errStr, _ := body["error"].(string)
	assert.NotEmpty(t, errStr)
}

func TestParseFile_MissingRequiredFields(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	tests := []string{
		`{}`,                                // both missing
		`{"content": ""}`,                   // empty content
		`{"path": ""}`,                      // empty path
		`{"content":"code here"}`,           // missing path
		`{"path":"file.go"}`,                // missing content
		`{"content":"", "path":"file.go"}`,  // empty content
		`{"content":"code here","path":""}`, // empty path
	}

	for _, payload := range tests {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")

		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code, "payload: %s", payload)
		var body map[string]any
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
		errStr, _ := body["error"].(string)
		assert.NotEmpty(t, errStr)
	}
}

func TestAnalyzeDiff_BadJSON(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(`{"old_content":`))
	req.Header.Set("Content-Type", "application/json")

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	errStr, _ := body["error"].(string)
	assert.NotEmpty(t, errStr)
}

func TestAnalyzeDiff_MissingRequiredFields(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	tests := []string{
		`{}`,                                    // both missing
		`{"old_content": ""}`,                   // empty old_content
		`{"new_content": ""}`,                   // empty new_content
		`{"old_content":"a"}`,                   // missing new_content
		`{"new_content":"b"}`,                   // missing old_content
		`{"old_content":"", "new_content":"b"}`, // empty old_content
		`{"old_content":"a", "new_content":""}`, // empty new_content
	}

	for _, payload := range tests {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")

		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code, "payload: %s", payload)
		var body map[string]any
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
		errStr, _ := body["error"].(string)
		assert.NotEmpty(t, errStr)
	}
}

func TestCalculateMetrics_BadJSON(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(`{"content":`))
	req.Header.Set("Content-Type", "application/json")

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	errStr, _ := body["error"].(string)
	assert.NotEmpty(t, errStr)
}

func TestCalculateMetrics_MissingRequiredField(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	tests := []string{
		`{}`,              // missing content
		`{"content": ""}`, // empty content
	}

	for _, payload := range tests {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(payload))
		req.Header.Set("Content-Type", "application/json")

		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code, "payload: %s", payload)
		var body map[string]any
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
		errStr, _ := body["error"].(string)
		assert.NotEmpty(t, errStr)
	}
}

func TestGetStatistics_BadJSON(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(`{"files":`))
	req.Header.Set("Content-Type", "application/json")

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	errStr, _ := body["error"].(string)
	assert.NotEmpty(t, errStr)
}

func TestGetStatistics_MissingFilesField(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")

	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	errStr, _ := body["error"].(string)
	assert.NotEmpty(t, errStr)
}

func TestGetStatistics_NestedMissingRequiredFields(t *testing.T) {
	h := NewHandler()
	router := setupRouter(h)

	// files present but elements missing required fields
	payloads := []string{
		`{"files":[{}]}`,
		`{"files":[{"content": ""}]}`,
		`{"files":[{"path": ""}]}`,
		`{"files":[{"content":"code"}]}`,
		`{"files":[{"path":"file.go"}]}`,
		`{"files":[{"content":"", "path":"file.go"}]}`,
		`{"files":[{"content":"code", "path":""}]}`,
	}

	for _, p := range payloads {
		w := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(p))
		req.Header.Set("Content-Type", "application/json")

		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code, "payload: %s", p)
		var body map[string]any
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
		errStr, _ := body["error"].(string)
		assert.NotEmpty(t, errStr)
	}
}
