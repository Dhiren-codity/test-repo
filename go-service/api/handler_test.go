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
	"github.com/stretchr/testify/require"
)

func setupRouter() (*gin.Engine, *Handler) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewHandler()

	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)

	return r, h
}

func doJSON(t *testing.T, r *gin.Engine, method, path string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		err := json.NewEncoder(&buf).Encode(body)
		require.NoError(t, err)
	}
	req := httptest.NewRequest(method, path, &buf)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)
	return rr
}

func doRaw(t *testing.T, r *gin.Engine, method, path, contentType string, rawBody string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(rawBody))
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)
	return rr
}

func TestHealthCheck_OK(t *testing.T) {
	r, _ := setupRouter()
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	r.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Contains(t, rr.Header().Get("Content-Type"), "application/json")

	var resp map[string]string
	require.NoError(t, json.Unmarshal(rr.Body.Bytes(), &resp))
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequests(t *testing.T) {
	r, _ := setupRouter()
	type errResp struct {
		Error string `json:"error"`
	}
	tests := []struct {
		name        string
		body        string
		contentType string
	}{
		{"no body", "", "application/json"},
		{"invalid json", "{", "application/json"},
		{"missing content", `{"path":"file.txt"}`, "application/json"},
		{"missing path", `{"content":"hello"}`, "application/json"},
		{"empty content", `{"content":"","path":"file.txt"}`, "application/json"},
		{"empty path", `{"content":"hello","path":""}`, "application/json"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRaw(t, r, http.MethodPost, "/parse", tt.contentType, tt.body)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var e errResp
			_ = json.Unmarshal(rr.Body.Bytes(), &e)
			assert.NotEmpty(t, e.Error)
		})
	}
}

func TestParseFile_MethodNotAllowed(t *testing.T) {
	r, _ := setupRouter()
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/parse", nil)
	r.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNotFound, rr.Code)
}

func TestAnalyzeDiff_BadRequests(t *testing.T) {
	r, _ := setupRouter()
	type errResp struct {
		Error string `json:"error"`
	}
	tests := []struct {
		name string
		body string
	}{
		{"no body", ""},
		{"invalid json", "{"},
		{"missing old_content", `{"new_content":"world"}`},
		{"missing new_content", `{"old_content":"hello"}`},
		{"empty old_content", `{"old_content":"","new_content":"x"}`},
		{"empty new_content", `{"old_content":"x","new_content":""}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRaw(t, r, http.MethodPost, "/diff", "application/json", tt.body)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var e errResp
			_ = json.Unmarshal(rr.Body.Bytes(), &e)
			assert.NotEmpty(t, e.Error)
		})
	}
}

func TestAnalyzeDiff_MethodNotAllowed(t *testing.T) {
	r, _ := setupRouter()
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/diff", nil)
	r.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNotFound, rr.Code)
}

func TestCalculateMetrics_BadRequests(t *testing.T) {
	r, _ := setupRouter()
	type errResp struct {
		Error string `json:"error"`
	}
	tests := []struct {
		name string
		body string
	}{
		{"no body", ""},
		{"invalid json", "{"},
		{"missing content", `{}`},
		{"empty content", `{"content":""}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRaw(t, r, http.MethodPost, "/metrics", "application/json", tt.body)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var e errResp
			_ = json.Unmarshal(rr.Body.Bytes(), &e)
			assert.NotEmpty(t, e.Error)
		})
	}
}

func TestCalculateMetrics_OK(t *testing.T) {
	r, _ := setupRouter()
	reqBody := map[string]string{"content": "hello world\nsecond line"}
	rr := doJSON(t, r, http.MethodPost, "/metrics", reqBody)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Contains(t, rr.Header().Get("Content-Type"), "application/json")

	var resp map[string]any
	require.NoError(t, json.Unmarshal(rr.Body.Bytes(), &resp))
	assert.NotEmpty(t, resp)
}

func TestCalculateMetrics_MethodNotAllowed(t *testing.T) {
	r, _ := setupRouter()
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	r.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNotFound, rr.Code)
}

func TestGetStatistics_BadRequests(t *testing.T) {
	r, _ := setupRouter()
	type errResp struct {
		Error string `json:"error"`
	}
	tests := []struct {
		name string
		body string
	}{
		{"no body", ""},
		{"invalid json", "{"},
		{"missing files", `{}`},
		{"empty files", `{"files":null}`},
		{"file missing content", `{"files":[null]}`},
		{"file missing path", `{"files":[1]}`},
		{"file empty content", `{"files":[{"content":"","path":"a.txt"}]}`},
		{"file empty path", `{"files":[{"content":"x","path":""}]}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRaw(t, r, http.MethodPost, "/statistics", "application/json", tt.body)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var e errResp
			_ = json.Unmarshal(rr.Body.Bytes(), &e)
			assert.NotEmpty(t, e.Error)
		})
	}
}

func TestGetStatistics_MethodNotAllowed(t *testing.T) {
	r, _ := setupRouter()
	rr := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/statistics", nil)
	r.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNotFound, rr.Code)
}
