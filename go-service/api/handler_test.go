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

func setupRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewHandler()
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)
	return r
}

func TestHealthCheck(t *testing.T) {
	router := setupRouter()

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rr := httptest.NewRecorder()
	router.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))

	var body map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &body)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", body["status"])
	assert.Equal(t, "go-parser", body["service"])
}

func TestParseFile_Validation(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing both fields",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing path",
			body:       `{"content":"code"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing content",
			body:       `{"path":"file.go"}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewBufferString(tt.body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			router.ServeHTTP(rr, req)

			assert.Equal(t, tt.wantStatus, rr.Code)
			assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
			var resp map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &resp)
			assert.Contains(t, resp, "error")
		})
	}
}

func TestAnalyzeDiff_Validation(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing both fields",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing new_content",
			body:       `{"old_content":"old"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing old_content",
			body:       `{"new_content":"new"}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/diff", bytes.NewBufferString(tt.body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			router.ServeHTTP(rr, req)

			assert.Equal(t, tt.wantStatus, rr.Code)
			assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
			var resp map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &resp)
			assert.Contains(t, resp, "error")
		})
	}
}

func TestCalculateMetrics_Validation(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing content",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/metrics", bytes.NewBufferString(tt.body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			router.ServeHTTP(rr, req)

			assert.Equal(t, tt.wantStatus, rr.Code)
			assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
			var resp map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &resp)
			assert.Contains(t, resp, "error")
		})
	}
}

func TestGetStatistics_Validation(t *testing.T) {
	router := setupRouter()

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       "",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing files field",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "files element missing content",
			body:       `{"files":[{"path":"a.go"}]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "files element missing path",
			body:       `{"files":[{"content":"package main"}]}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/statistics", bytes.NewBufferString(tt.body))
			req.Header.Set("Content-Type", "application/json")
			rr := httptest.NewRecorder()

			router.ServeHTTP(rr, req)

			assert.Equal(t, tt.wantStatus, rr.Code)
			assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
			var resp map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &resp)
			assert.Contains(t, resp, "error")
		})
	}
}
