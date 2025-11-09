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

func doPost(r *gin.Engine, path string, body string) *httptest.ResponseRecorder {
	var reader *bytes.Reader
	if body != "" {
		reader = bytes.NewReader([]byte(body))
	} else {
		reader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(http.MethodPost, path, reader)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	defer func() {
		if rec := recover(); rec != nil {
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(`{"error":"internal server error"}`))
		}
	}()
	r.ServeHTTP(w, req)
	return w
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

func TestParseFile_MethodNotAllowedOrNotFound(t *testing.T) {
	r := setupRouter()

	req := httptest.NewRequest(http.MethodGet, "/parse", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	// Route not registered for GET, expect 404
	assert.Equal(t, http.StatusNotFound, w.Code)
}

func TestParseFile_BadRequest_BindingErrors(t *testing.T) {
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
			name:       "invalid json",
			body:       "not json",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing required fields",
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
			w := doPost(r, "/parse", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			assert.True(t, strings.Contains(w.Body.String(), "error"))
		})
	}
}

func TestAnalyzeDiff_BadRequest_BindingErrors(t *testing.T) {
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
			name:       "invalid json",
			body:       "not json",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing required fields",
			body:       `{}`,
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
		t.Run(tt.name, func(t *testing.T) {
			w := doPost(r, "/diff", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			assert.True(t, strings.Contains(w.Body.String(), "error"))
		})
	}
}

func TestCalculateMetrics_BadRequest_BindingErrors(t *testing.T) {
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
			name:       "invalid json",
			body:       "not json",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing required fields",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "content empty string still provided",
			body:       `{"content":""}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "valid content",
			body:       `{"content":"some code"}`,
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doPost(r, "/metrics", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
		})
	}
}

func TestGetStatistics_BadRequest_BindingErrors(t *testing.T) {
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
			name:       "invalid json",
			body:       "not json",
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing required files field",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "files null",
			body:       `{"files":null}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "files item missing fields",
			body:       `{"files":[{}]}`,
			wantStatus: http.StatusInternalServerError,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doPost(r, "/statistics", tt.body)
			assert.Equal(t, tt.wantStatus, w.Code)
			if tt.wantStatus == http.StatusBadRequest {
				assert.True(t, strings.Contains(w.Body.String(), "error"))
			}
		})
	}
}
