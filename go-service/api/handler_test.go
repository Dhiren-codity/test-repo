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

	r.POST("/api/parse", h.ParseFile)
	r.POST("/api/diff", h.AnalyzeDiff)
	r.POST("/api/metrics", h.CalculateMetrics)
	r.POST("/api/statistics", h.GetStatistics)
	r.GET("/healthz", h.HealthCheck)

	return r
}

func doRequest(r *gin.Engine, method, url, body string) *httptest.ResponseRecorder {
	var reader *strings.Reader
	if body != "" {
		reader = strings.NewReader(body)
	} else {
		reader = strings.NewReader("")
	}
	req := httptest.NewRequest(method, url, reader)
	if method == http.MethodPost || method == http.MethodPut || method == http.MethodDelete {
		req.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestHealthCheck_OK(t *testing.T) {
	r := setupRouter()

	w := doRequest(r, http.MethodGet, "/healthz", "")

	assert.Equal(t, http.StatusOK, w.Code)
	var resp map[string]string
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest(t *testing.T) {
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
			name:       "missing content",
			body:       `{"path":"main.go"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing path",
			body:       `{"content":"package main\nfunc main(){}"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{"content": "x", "path": "main.go"`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/api/parse", tt.body)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error in response")
		})
	}
}

func TestParseFile_Success(t *testing.T) {
	r := setupRouter()

	body := `{"content":"package main\nfunc main(){}", "path":"main.go"}`
	w := doRequest(r, http.MethodPost, "/api/parse", body)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
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
			name:       "missing old_content",
			body:       `{"new_content":"b"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "missing new_content",
			body:       `{"old_content":"a"}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{"old_content":"a", "new_content":"b"`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/api/diff", tt.body)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error in response")
		})
	}
}

func TestAnalyzeDiff_Success(t *testing.T) {
	r := setupRouter()

	body := `{"old_content":"a", "new_content":"b"}`
	w := doRequest(r, http.MethodPost, "/api/diff", body)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
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
			name:       "missing content",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{"content":"x"`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/api/metrics", tt.body)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error in response")
		})
	}
}

func TestCalculateMetrics_Success(t *testing.T) {
	r := setupRouter()

	body := `{"content":"some content"}`
	w := doRequest(r, http.MethodPost, "/api/metrics", body)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestGetStatistics_BadRequest(t *testing.T) {
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
			name:       "missing files field",
			body:       `{}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "file missing required field",
			body:       `{"files":[{"path":"a.go"}]}`,
			wantStatus: http.StatusBadRequest,
		},
		{
			name:       "invalid json",
			body:       `{"files":[{"content":"x","path":"a.go"}]`,
			wantStatus: http.StatusBadRequest,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := doRequest(r, http.MethodPost, "/api/statistics", tt.body)

			assert.Equal(t, tt.wantStatus, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error in response")
		})
	}
}

func TestGetStatistics_Success(t *testing.T) {
	r := setupRouter()

	body := `{"files":[{"content":"package main\nfunc main(){}", "path":"main.go"}]}`
	w := doRequest(r, http.MethodPost, "/api/statistics", body)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
}

func TestUnsupportedMethods_ReturnNotFound(t *testing.T) {
	r := setupRouter()

	// PUT to a POST endpoint should 404
	w1 := doRequest(r, http.MethodPut, "/api/parse", `{"content":"x","path":"a.go"}`)
	assert.Equal(t, http.StatusNotFound, w1.Code)

	// DELETE to a POST endpoint should 404
	w2 := doRequest(r, http.MethodDelete, "/api/metrics", `{"content":"x"}`)
	assert.Equal(t, http.StatusNotFound, w2.Code)
}
