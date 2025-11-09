package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

var setModeOnce sync.Once

func setupRouter(h *Handler) *gin.Engine {
	setModeOnce.Do(func() {
		gin.SetMode(gin.TestMode)
	})
	r := gin.New()
	r.Use(gin.Recovery())
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)
	return r
}

func doRequest(r http.Handler, method, path, body string) *httptest.ResponseRecorder {
	var reader *strings.Reader
	if body != "" {
		reader = strings.NewReader(body)
	} else {
		reader = strings.NewReader("")
	}
	req := httptest.NewRequest(method, path, reader)
	if method == http.MethodPost || method == http.MethodPut || method == http.MethodPatch {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck_OK(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

	w := doRequest(r, http.MethodGet, "/health", "")
	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]string
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
}

func TestParseFile_BindingErrors(t *testing.T) {
	t.Parallel()
	h := &Handler{} // parser not needed for binding error tests
	r := setupRouter(h)

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
			body:       `{"path":"file.go"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing path",
			body:       `{"content":"package main"}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/parse", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestParseFile_WrongMethod(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

	w := doRequest(r, http.MethodGet, "/parse", "")
	assert.Equal(t, http.StatusNotFound, w.Code) // route not registered for GET
}

func TestAnalyzeDiff_BindingErrors(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

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
			name:       "missing old_content",
			body:       `{"new_content":"new"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing new_content",
			body:       `{"old_content":"old"}`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/diff", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestAnalyzeDiff_WrongMethod(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

	w := doRequest(r, http.MethodGet, "/diff", "")
	assert.Equal(t, http.StatusNotFound, w.Code) // route not registered for GET
}

func TestCalculateMetrics_BindingErrors(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

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
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/metrics", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestGetStatistics_BindingErrors(t *testing.T) {
	t.Parallel()
	h := &Handler{}
	r := setupRouter(h)

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
			name:       "files null",
			body:       `{"files":null}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "files empty array (required fails)",
			body:       `{"files":[]}`,
			wantStatus: http.StatusInternalServerError,
		},
		{
			name:       "file missing content",
			body:       `{"files":[{"path":"a.go"}]}`,
			wantStatus: http.StatusInternalServerError,
		},
		{
			name:       "file missing path",
			body:       `{"files":[{"content":"package main"}]}`,
			wantStatus: http.StatusInternalServerError,
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/statistics", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			if tt.wantStatus == http.StatusBadRequest {
				assert.Contains(t, w.Body.String(), "error")
			}
		})
	}
}
