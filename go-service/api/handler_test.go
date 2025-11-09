package api

import (
	"bytes"
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

	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)

	return r
}

func TestHealthCheck_OK(t *testing.T) {
	r := setupRouter()

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))

	var body map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &body)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", body["status"])
	assert.Equal(t, "go-parser", body["service"])
}

func TestParseFile_BindingErrors(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name       string
		body       string
		setHeader  bool
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       "",
			setHeader:  true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid JSON",
			body:       "{",
			setHeader:  true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing content",
			body:       `{"path":"file.go"}`,
			setHeader:  true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing path",
			body:       `{"content":"package main"}`,
			setHeader:  true,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "no content-type header still errors on missing fields",
			body:       `{"path":"file.go"}`,
			setHeader:  false,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var bodyReader *strings.Reader
			if tt.body != "" {
				bodyReader = strings.NewReader(tt.body)
			} else {
				bodyReader = strings.NewReader("")
			}
			req := httptest.NewRequest(http.MethodPost, "/parse", bodyReader)
			if tt.setHeader {
				req.Header.Set("Content-Type", "application/json")
			}
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestAnalyzeDiff_BindingErrors(t *testing.T) {
	r := setupRouter()

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
			name:       "invalid JSON",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing old_content",
			body:       `{"new_content":"new"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing new_content",
			body:       `{"old_content":"old"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "wrong keys",
			body:       `{"oldContent":"x","newContent":"y"}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestCalculateMetrics_StatusCodes(t *testing.T) {
	r := setupRouter()

	t.Run("bad request - missing content", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(`{}`))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
		var resp map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &resp)
		_, hasErr := resp["error"]
		assert.True(t, hasErr, "expected error field in response")
	})

	t.Run("invalid JSON", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(`{`))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})

	t.Run("ok - valid content", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/metrics", bytes.NewBufferString(`{"content":"package main"}`))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)

		// Expect 200 because CalculateMetrics does not return error according to handler
		assert.Equal(t, http.StatusOK, w.Code)
		assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
	})
}

func TestGetStatistics_BindingErrors(t *testing.T) {
	r := setupRouter()

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
			name:       "invalid JSON",
			body:       "{",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing files",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file item missing content",
			body:       `{"files":[{"path":"a.go"}]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file item missing path",
			body:       `{"files":[{"content":"package main"}]}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestMethodRouting(t *testing.T) {
	r := setupRouter()

	tests := []struct {
		name       string
		method     string
		target     string
		wantStatus int
	}{
		{"GET parse not allowed", http.MethodGet, "/parse", http.StatusNotFound},
		{"PUT diff not allowed", http.MethodPut, "/diff", http.StatusNotFound},
		{"DELETE metrics not allowed", http.MethodDelete, "/metrics", http.StatusNotFound},
		{"GET statistics not allowed", http.MethodGet, "/statistics", http.StatusNotFound},
		{"POST health not allowed", http.MethodPost, "/health", http.StatusNotFound},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.target, nil)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			assert.Equal(t, tt.wantStatus, w.Code)
		})
	}
}
