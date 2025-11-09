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

func TestHealthCheck(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

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

func TestHealthCheck_MethodNotAllowed(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	req := httptest.NewRequest(http.MethodPost, "/health", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	// Gin by default returns 404 for methods not registered unless HandleMethodNotAllowed is enabled.
	assert.Equal(t, http.StatusNotFound, w.Code)
}

func TestParseFile_BadRequests(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       ``,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{invalid`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing content",
			body:       `{"path":"main.go"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing path",
			body:       `{"content":"package main"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "empty required fields",
			body:       `{"content":"","path":""}`,
			wantStatus: http.StatusBadRequest,
		},
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

			assert.Equal(t, tt.wantStatus, w.Code)
			assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			assert.NotEmpty(t, resp["error"])
		})
	}
}

func TestParseFile_Success(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	body := `{"content":"package main\nfunc main(){}","path":"main.go"}`
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
	// Response shape is not strictly defined; ensure it's valid JSON
	var any map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &any)
	assert.NoError(t, err)
}

func TestAnalyzeDiff_BadRequests(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       ``,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{invalid`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing old content",
			body:       `{"new_content":"new"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing new content",
			body:       `{"old_content":"old"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "empty required fields",
			body:       `{"old_content":"","new_content":""}`,
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
			assert.NotEmpty(t, resp["error"])
		})
	}
}

func TestAnalyzeDiff_Success(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	body := `{"old_content":"package main\nfunc A(){}","new_content":"package main\nfunc A(){}\nfunc B(){}"}`
	req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
	var any map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &any)
	assert.NoError(t, err)
}

func TestCalculateMetrics_BadRequests(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       ``,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{invalid`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing content",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "empty content",
			body:       `{"content":""}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(tt.body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			assert.NotEmpty(t, resp["error"])
		})
	}
}

func TestCalculateMetrics_Success(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	body := `{"content":"package main\nfunc main(){\n // test\n}\n"}`
	req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
	var any map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &any)
	assert.NoError(t, err)
}

func TestGetStatistics_BadRequests(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name       string
		body       string
		wantStatus int
	}{
		{
			name:       "empty body",
			body:       ``,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{invalid`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing files",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "empty files slice",
			body:       `{"files":[]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file missing content",
			body:       `{"files":[{"path":"a.go"}]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file missing path",
			body:       `{"files":[{"content":"package main"}]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file empty required fields",
			body:       `{"files":[{"content":"","path":""}]}`,
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
			assert.NotEmpty(t, resp["error"])
		})
	}
}

func TestGetStatistics_Success(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	body := `{"files":[{"content":"package main\nfunc A(){}","path":"a.go"},{"content":"package main\nfunc B(){}","path":"b.go"}]}`
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Equal(t, "application/json; charset=utf-8", w.Header().Get("Content-Type"))
	var any map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &any)
	assert.NoError(t, err)
}

func TestEndpoints_WrongMethodsReturnNotFound(t *testing.T) {
	h := NewHandler()
	r := setupRouter(h)

	tests := []struct {
		name   string
		method string
		url    string
	}{
		{"GET parse", http.MethodGet, "/parse"},
		{"PUT parse", http.MethodPut, "/parse"},
		{"DELETE parse", http.MethodDelete, "/parse"},
		{"GET diff", http.MethodGet, "/diff"},
		{"PUT diff", http.MethodPut, "/diff"},
		{"DELETE diff", http.MethodDelete, "/diff"},
		{"GET metrics", http.MethodGet, "/metrics"},
		{"PUT metrics", http.MethodPut, "/metrics"},
		{"DELETE metrics", http.MethodDelete, "/metrics"},
		{"GET statistics", http.MethodGet, "/statistics"},
		{"PUT statistics", http.MethodPut, "/statistics"},
		{"DELETE statistics", http.MethodDelete, "/statistics"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.url, nil)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			assert.Equal(t, http.StatusNotFound, w.Code)
		})
	}
}
