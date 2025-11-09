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
	r.GET("/healthz", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	return r
}

func doRequest(t *testing.T, r http.Handler, method, path string, body string, contentType string) *httptest.ResponseRecorder {
	t.Helper()
	var reader *strings.Reader
	if body != "" {
		reader = strings.NewReader(body)
	} else {
		reader = strings.NewReader("")
	}
	req := httptest.NewRequest(method, path, reader)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func parseJSON(t *testing.T, data []byte) map[string]interface{} {
	t.Helper()
	var out map[string]interface{}
	err := json.Unmarshal(data, &out)
	if err != nil {
		t.Fatalf("failed to unmarshal json: %v; body: %s", err, string(data))
	}
	return out
}

func TestHealthCheck_OK(t *testing.T) {
	router := setupRouter()
	rr := doRequest(t, router, http.MethodGet, "/healthz", "", "")
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	resp := parseJSON(t, rr.Body.Bytes())
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequests(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
		wantStatus  int
	}{
		{
			name:        "invalid json",
			body:        "{",
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing all fields",
			body:        `{}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing path",
			body:        `{"content":"code here"}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing content",
			body:        `{"path":"file.go"}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "wrong content type",
			body:        `{"content":"x","path":"a"}`,
			contentType: "text/plain",
			wantStatus:  http.StatusBadRequest,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRequest(t, router, http.MethodPost, "/parse", tt.body, tt.contentType)
			assert.Equal(t, tt.wantStatus, rr.Code, rr.Body.String())
			resp := parseJSON(t, rr.Body.Bytes())
			_, ok := resp["error"]
			assert.True(t, ok, "expected error field in response")
		})
	}

	t.Run("method not allowed/route not found", func(t *testing.T) {
		rr := doRequest(t, router, http.MethodGet, "/parse", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestAnalyzeDiff_BadRequests(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
		wantStatus  int
	}{
		{
			name:        "invalid json",
			body:        "{",
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing all fields",
			body:        `{}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing old_content",
			body:        `{"new_content":"bar"}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing new_content",
			body:        `{"old_content":"foo"}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "wrong content type",
			body:        `{"old_content":"a","new_content":"b"}`,
			contentType: "text/plain",
			wantStatus:  http.StatusBadRequest,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRequest(t, router, http.MethodPost, "/diff", tt.body, tt.contentType)
			assert.Equal(t, tt.wantStatus, rr.Code, rr.Body.String())
			resp := parseJSON(t, rr.Body.Bytes())
			_, ok := resp["error"]
			assert.True(t, ok, "expected error field in response")
		})
	}

	t.Run("method not allowed/route not found", func(t *testing.T) {
		rr := doRequest(t, router, http.MethodGet, "/diff", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestCalculateMetrics_BadRequests(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
		wantStatus  int
	}{
		{
			name:        "invalid json",
			body:        "{",
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing content",
			body:        `{}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "wrong content type",
			body:        `{"content":"anything"}`,
			contentType: "text/plain",
			wantStatus:  http.StatusBadRequest,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRequest(t, router, http.MethodPost, "/metrics", tt.body, tt.contentType)
			assert.Equal(t, tt.wantStatus, rr.Code, rr.Body.String())
			resp := parseJSON(t, rr.Body.Bytes())
			_, ok := resp["error"]
			assert.True(t, ok, "expected error field in response")
		})
	}

	t.Run("method not allowed/route not found", func(t *testing.T) {
		rr := doRequest(t, router, http.MethodGet, "/metrics", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestGetStatistics_BadRequests(t *testing.T) {
	router := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
		wantStatus  int
		validate    func(t *testing.T, rr *httptest.ResponseRecorder)
	}{
		{
			name:        "invalid json",
			body:        "{",
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "missing files",
			body:        `{}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "files wrong type",
			body:        `{"files": 123}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "file missing content",
			body:        `{"files":[{"path":"a.go"}]}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "file missing path",
			body:        `{"files":[{"content":"package main"}]}`,
			contentType: "application/json",
			wantStatus:  http.StatusBadRequest,
		},
		{
			name:        "wrong content type",
			body:        `{"files":[{"content":"x","path":"a"}]}`,
			contentType: "text/plain",
			wantStatus:  http.StatusBadRequest,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doRequest(t, router, http.MethodPost, "/statistics", tt.body, tt.contentType)
			assert.Equal(t, tt.wantStatus, rr.Code, rr.Body.String())
			resp := parseJSON(t, rr.Body.Bytes())
			_, ok := resp["error"]
			assert.True(t, ok, "expected error field in response")
		})
	}

	t.Run("method not allowed/route not found", func(t *testing.T) {
		rr := doRequest(t, router, http.MethodGet, "/statistics", "", "")
		// Only POST route exists; GET should be 404
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestContentTypeMissing_ReturnsBadRequest(t *testing.T) {
	router := setupRouter()
	// Test each JSON-binding endpoint without Content-Type
	cases := []struct {
		path string
		body string
	}{
		{path: "/parse", body: `{"content":"x","path":"a"}`},
		{path: "/diff", body: `{"old_content":"x","new_content":"y"}`},
		{path: "/metrics", body: `{"content":"x"}`},
		{path: "/statistics", body: `{"files":[{"content":"x","path":"a"}]}`},
	}
	for _, c := range cases {
		rr := doRequest(t, router, http.MethodPost, c.path, c.body, "")
		assert.Equal(t, http.StatusBadRequest, rr.Code, "path=%s body=%s", c.path, c.body)
		resp := parseJSON(t, rr.Body.Bytes())
		_, ok := resp["error"]
		assert.True(t, ok, "expected error field in response")
	}
}

func TestJSONResponseContentType(t *testing.T) {
	router := setupRouter()
	rr := doRequest(t, router, http.MethodGet, "/healthz", "", "")
	assert.Equal(t, http.StatusOK, rr.Code)
	ct := rr.Header().Get("Content-Type")
	assert.True(t, strings.HasPrefix(ct, "application/json"), ct)
}

func TestErrorResponseIsJSON(t *testing.T) {
	router := setupRouter()
	rr := doRequest(t, router, http.MethodPost, "/parse", `{}`, "application/json")
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	ct := rr.Header().Get("Content-Type")
	assert.True(t, strings.HasPrefix(ct, "application/json"))
	buf := bytes.TrimSpace(rr.Body.Bytes())
	assert.True(t, len(buf) > 0)
	var m map[string]interface{}
	err := json.Unmarshal(buf, &m)
	assert.NoError(t, err)
	_, ok := m["error"]
	assert.True(t, ok)
}
