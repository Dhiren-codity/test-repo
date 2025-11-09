package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func setupRouter(h *Handler) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/health", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	return r
}

func doRequest(r *gin.Engine, method, path string, body []byte) *httptest.ResponseRecorder {
	var req *http.Request
	if body != nil {
		req = httptest.NewRequest(method, path, bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
	} else {
		req = httptest.NewRequest(method, path, nil)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck_OK(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := doRequest(r, http.MethodGet, "/health", nil)
	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]string
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_InvalidJSON(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	w := doRequest(r, http.MethodPost, "/parse", []byte("{invalid"))
	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestParseFile_MissingRequiredFields(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Missing both fields
	w := doRequest(r, http.MethodPost, "/parse", []byte(`{}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Missing path
	w = doRequest(r, http.MethodPost, "/parse", []byte(`{"content":"code"}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Missing content
	w = doRequest(r, http.MethodPost, "/parse", []byte(`{"path":"file.go"}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Empty required fields
	w = doRequest(r, http.MethodPost, "/parse", []byte(`{"content":"","path":""}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestAnalyzeDiff_MissingRequiredFields(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Missing both fields
	w := doRequest(r, http.MethodPost, "/diff", []byte(`{}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Missing new_content
	w = doRequest(r, http.MethodPost, "/diff", []byte(`{"old_content":"old"}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Missing old_content
	w = doRequest(r, http.MethodPost, "/diff", []byte(`{"new_content":"new"}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Empty required fields
	w = doRequest(r, http.MethodPost, "/diff", []byte(`{"old_content":"","new_content":""}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestCalculateMetrics_MissingRequiredFields(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Missing content
	w := doRequest(r, http.MethodPost, "/metrics", []byte(`{}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)

	// Empty content
	w = doRequest(r, http.MethodPost, "/metrics", []byte(`{"content":""}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestGetStatistics_MissingFilesField(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// Missing files
	w := doRequest(r, http.MethodPost, "/statistics", []byte(`{}`))
	assert.Equal(t, http.StatusBadRequest, w.Code)
}

func TestGetStatistics_FileItemsValidation(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	// files present but items missing required fields
	body := []byte(`{"files":[{"content":"code"},{"path":"file.go"},{"content":"","path":""}]}`)
	w := doRequest(r, http.MethodPost, "/statistics", body)
	assert.Equal(t, http.StatusBadRequest, w.Code)
}
