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
	r := gin.New()
	h := NewHandler()

	r.GET("/health", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)

	return r
}

func TestHealthCheck_OK(t *testing.T) {
	r := setupRouter()

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", got["status"])
	assert.Equal(t, "go-parser", got["service"])
}

func TestParseFile_ValidationErrors(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{"empty_body", ""},
		{"invalid_json", "{"},
		{"missing_path", `{"content":"package main"}`},
		{"missing_content", `{"path":"main.go"}`},
		{"empty_fields", `{"content":"","path":""}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var reader *strings.Reader
			if tt.body == "" {
				reader = strings.NewReader("")
			} else {
				reader = strings.NewReader(tt.body)
			}
			req := httptest.NewRequest(http.MethodPost, "/parse", reader)
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var got map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &got)
			_, hasErr := got["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestParseFile_Success(t *testing.T) {
	r := setupRouter()

	body := `{"content":"package main\n","path":"main.go"}`
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
}

func TestAnalyzeDiff_ValidationErrors(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{"empty_body", ""},
		{"invalid_json", "{"},
		{"missing_old", `{"new_content":"b"}`},
		{"missing_new", `{"old_content":"a"}`},
		{"empty_fields", `{"old_content":"","new_content":""}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var got map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &got)
			_, hasErr := got["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestAnalyzeDiff_Success(t *testing.T) {
	r := setupRouter()

	body := `{"old_content":"a\nb\nc","new_content":"a\nc\nd"}`
	req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
}

func TestCalculateMetrics_ValidationErrors(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{"empty_body", ""},
		{"invalid_json", "{"},
		{"missing_content", `{}`},
		{"empty_content", `{"content":""}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var got map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &got)
			_, hasErr := got["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestCalculateMetrics_Success(t *testing.T) {
	r := setupRouter()

	body := `{"content":"one two\nthree"}`
	req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
}

func TestGetStatistics_ValidationErrors(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name string
		body string
	}{
		{"empty_body", ""},
		{"invalid_json", "{"},
		{"missing_files", `{}`},
		{"empty_files", `{"files":[]}`},
		{"file_missing_content", `{"files":[{"path":"a.go"}]}`},
		{"file_missing_path", `{"files":[{"content":"package main"}]}`},
		{"file_empty_fields", `{"files":[{"content":"","path":""}]}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var got map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &got)
			_, hasErr := got["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestGetStatistics_Success(t *testing.T) {
	r := setupRouter()

	body := `{"files":[{"content":"package main\nfunc main(){}","path":"main.go"}]}`
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
}
