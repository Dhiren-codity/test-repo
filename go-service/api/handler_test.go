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

	r.GET("/health", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)

	return r
}

func TestHealthCheck_OK(t *testing.T) {
	router := setupRouter()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	var resp map[string]interface{}
	err := json.Unmarshal(rec.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_MethodNotAllowed(t *testing.T) {
	router := setupRouter()
	req := httptest.NewRequest(http.MethodGet, "/parse", nil)
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNotFound, rec.Code)
}

func TestParseFile_BadRequest(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{
			name: "empty body",
			body: "",
		},
		{
			name: "invalid json",
			body: "{",
		},
		{
			name: "missing content",
			body: `{"path":"main.go"}`,
		},
		{
			name: "missing path",
			body: `{"content":"package main"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var body *bytes.Reader
			if tt.body != "" {
				body = bytes.NewReader([]byte(tt.body))
			} else {
				body = bytes.NewReader(nil)
			}
			req := httptest.NewRequest(http.MethodPost, "/parse", body)
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()

			router.ServeHTTP(rec, req)

			assert.Equal(t, http.StatusBadRequest, rec.Code)
			assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
			var resp map[string]interface{}
			_ = json.Unmarshal(rec.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr)
		})
	}
}

func TestParseFile_Success(t *testing.T) {
	router := setupRouter()
	payload := ParseRequest{
		Content: "package main\nfunc main(){}",
		Path:    "main.go",
	}
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	// Response shape depends on parser; ensure it's valid JSON
	var resp interface{}
	err := json.Unmarshal(rec.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{
			name: "empty body",
			body: "",
		},
		{
			name: "invalid json",
			body: "{",
		},
		{
			name: "missing both",
			body: `{"old_content":"","new_content":""}`,
		},
		{
			name: "missing old_content",
			body: `{"new_content":"new"}`,
		},
		{
			name: "missing new_content",
			body: `{"old_content":"old"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var body *bytes.Reader
			if tt.body != "" {
				body = bytes.NewReader([]byte(tt.body))
			} else {
				body = bytes.NewReader(nil)
			}
			req := httptest.NewRequest(http.MethodPost, "/diff", body)
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()

			router.ServeHTTP(rec, req)

			assert.Equal(t, http.StatusBadRequest, rec.Code)
			assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
			var resp map[string]interface{}
			_ = json.Unmarshal(rec.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr)
		})
	}
}

func TestAnalyzeDiff_Success(t *testing.T) {
	router := setupRouter()
	payload := DiffRequest{
		OldContent: "package main\nfunc main(){}",
		NewContent: "package main\nfunc main(){println(\"hi\")}",
	}
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/diff", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	var resp interface{}
	err := json.Unmarshal(rec.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{
			name: "empty body",
			body: "",
		},
		{
			name: "invalid json",
			body: "{",
		},
		{
			name: "missing content",
			body: `{}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var body *bytes.Reader
			if tt.body != "" {
				body = bytes.NewReader([]byte(tt.body))
			} else {
				body = bytes.NewReader(nil)
			}
			req := httptest.NewRequest(http.MethodPost, "/metrics", body)
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()

			router.ServeHTTP(rec, req)

			assert.Equal(t, http.StatusBadRequest, rec.Code)
			assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
			var resp map[string]interface{}
			_ = json.Unmarshal(rec.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr)
		})
	}
}

func TestCalculateMetrics_Success(t *testing.T) {
	router := setupRouter()
	payload := MetricsRequest{
		Content: "package main\nfunc main(){}",
	}
	b, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, "/metrics", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code, "body=%s", rec.Body.String())
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	var resp interface{}
	err := json.Unmarshal(rec.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestGetStatistics_BadRequest(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{
			name: "empty body",
			body: "",
		},
		{
			name: "invalid json",
			body: "{",
		},
		{
			name: "missing files field",
			body: `{}`,
		},
		{
			name: "file missing content",
			body: `{"files":[{"path":"main.go"}]}`,
		},
		{
			name: "file missing path",
			body: `{"files":[{"content":"package main"}]}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var body *bytes.Reader
			if tt.body != "" {
				body = bytes.NewReader([]byte(tt.body))
			} else {
				body = bytes.NewReader(nil)
			}
			req := httptest.NewRequest(http.MethodPost, "/statistics", body)
			req.Header.Set("Content-Type", "application/json")
			rec := httptest.NewRecorder()

			router.ServeHTTP(rec, req)

			assert.Equal(t, http.StatusBadRequest, rec.Code)
			assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
			var resp map[string]interface{}
			_ = json.Unmarshal(rec.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr)
		})
	}
}

func TestGetStatistics_Success(t *testing.T) {
	router := setupRouter()
	body := `{"files":[{"content":"package main\nfunc main(){}", "path":"main.go"}]}`
	req := httptest.NewRequest(http.MethodPost, "/statistics", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()

	router.ServeHTTP(rec, req)

	// Expect either OK (preferred) or InternalServerError if parser fails internally.
	// The handler's contract for valid input is 200 unless parser returns an error.
	if rec.Code != http.StatusOK {
		// Surface body for debugging
		t.Fatalf("expected 200, got %d; body=%s", rec.Code, rec.Body.String())
	}
	assert.Contains(t, rec.Header().Get("Content-Type"), "application/json")
	var resp interface{}
	err := json.Unmarshal(rec.Body.Bytes(), &resp)
	assert.NoError(t, err)
}
