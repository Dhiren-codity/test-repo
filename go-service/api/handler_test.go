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

func setupRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	h := NewHandler()

	r := gin.New()
	// Register routes
	r.GET("/health", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)

	return r
}

func performRequest(r http.Handler, method, path, body string) *httptest.ResponseRecorder {
	var reader *strings.Reader
	if body != "" {
		reader = strings.NewReader(body)
	} else {
		reader = strings.NewReader("")
	}
	req := httptest.NewRequest(method, path, reader)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck_OK(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodGet, "/health", "")

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadJSON_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/parse", "{")

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestParseFile_MissingFields_Returns400(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{
			name: "missing content",
			body: `{"path":"main.go"}`,
		},
		{
			name: "missing path",
			body: `{"content":"package main"}`,
		},
		{
			name: "empty body",
			body: `{}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(router, http.MethodPost, "/parse", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestParseFile_WrongMethod_Returns404(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodGet, "/parse", "")

	// Gin returns 404 when method not registered for a path
	assert.Equal(t, http.StatusNotFound, w.Code)
}

func TestAnalyzeDiff_BadJSON_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/diff", "{")

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestAnalyzeDiff_MissingFields_Returns400(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{
			name: "missing old_content",
			body: `{"new_content":"new"}`,
		},
		{
			name: "missing new_content",
			body: `{"old_content":"old"}`,
		},
		{
			name: "empty body",
			body: `{}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(router, http.MethodPost, "/diff", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestCalculateMetrics_BadJSON_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/metrics", "{")

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestCalculateMetrics_MissingContent_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/metrics", `{}`)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestGetStatistics_BadJSON_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/statistics", "{")

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}

func TestGetStatistics_MissingFiles_Returns400(t *testing.T) {
	router := setupRouter()

	w := performRequest(router, http.MethodPost, "/statistics", `{}`)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "error")
}
