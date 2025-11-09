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
	h := NewHandler()
	r := gin.New()
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)
	return r
}

func doJSONRequest(t *testing.T, r http.Handler, method, path string, body string, contentType string) *httptest.ResponseRecorder {
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
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)
	return rr
}

func TestHealthCheck_OK(t *testing.T) {
	r := setupRouter()
	rr := doJSONRequest(t, r, http.MethodGet, "/health", "", "")
	assert.Equal(t, http.StatusOK, rr.Code)

	var m map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &m)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", m["status"])
	assert.Equal(t, "go-parser", m["service"])
}

func TestParseFile_BadRequests(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
	}{
		{
			name:        "empty body with content-type",
			body:        `{}`,
			contentType: "application/json",
		},
		{
			name:        "missing content",
			body:        `{"path":"main.go"}`,
			contentType: "application/json",
		},
		{
			name:        "missing path",
			body:        `{"content":"package main"}`,
			contentType: "application/json",
		},
		{
			name:        "invalid json",
			body:        `{`,
			contentType: "application/json",
		},
		{
			name:        "no content-type set",
			body:        `{"content":"x","path":"a.go"}`,
			contentType: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doJSONRequest(t, r, http.MethodPost, "/parse", tt.body, tt.contentType)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var m map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &m)
			_, hasError := m["error"]
			assert.True(t, hasError)
		})
	}

	t.Run("wrong method returns 404", func(t *testing.T) {
		rr := doJSONRequest(t, r, http.MethodGet, "/parse", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestAnalyzeDiff_BadRequests(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
	}{
		{
			name:        "empty body",
			body:        `{}`,
			contentType: "application/json",
		},
		{
			name:        "missing old_content",
			body:        `{"new_content":"world"}`,
			contentType: "application/json",
		},
		{
			name:        "missing new_content",
			body:        `{"old_content":"hello"}`,
			contentType: "application/json",
		},
		{
			name:        "invalid json",
			body:        `{`,
			contentType: "application/json",
		},
		{
			name:        "no content-type set",
			body:        `{"old_content":"a","new_content":"b"}`,
			contentType: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doJSONRequest(t, r, http.MethodPost, "/diff", tt.body, tt.contentType)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var m map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &m)
			_, hasError := m["error"]
			assert.True(t, hasError)
		})
	}

	t.Run("wrong method returns 404", func(t *testing.T) {
		rr := doJSONRequest(t, r, http.MethodGet, "/diff", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestCalculateMetrics_BadRequests(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
	}{
		{
			name:        "empty body",
			body:        `{}`,
			contentType: "application/json",
		},
		{
			name:        "invalid json",
			body:        `{`,
			contentType: "application/json",
		},
		{
			name:        "no content-type set",
			body:        `{"content":"package main"}`,
			contentType: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doJSONRequest(t, r, http.MethodPost, "/metrics", tt.body, tt.contentType)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var m map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &m)
			_, hasError := m["error"]
			assert.True(t, hasError)
		})
	}

	t.Run("wrong method returns 404", func(t *testing.T) {
		rr := doJSONRequest(t, r, http.MethodGet, "/metrics", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestGetStatistics_BadRequests(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name        string
		body        string
		contentType string
	}{
		{
			name:        "empty body",
			body:        `{}`,
			contentType: "application/json",
		},
		{
			name:        "files wrong type",
			body:        `{"files":"not-an-array"}`,
			contentType: "application/json",
		},
		{
			name:        "file item missing required fields",
			body:        `{"files":[{}]}`,
			contentType: "application/json",
		},
		{
			name:        "invalid json",
			body:        `{`,
			contentType: "application/json",
		},
		{
			name:        "no content-type set",
			body:        `{"files":[{"content":"x","path":"a.go"}]}`,
			contentType: "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rr := doJSONRequest(t, r, http.MethodPost, "/statistics", tt.body, tt.contentType)
			assert.Equal(t, http.StatusBadRequest, rr.Code)
			var m map[string]any
			_ = json.Unmarshal(rr.Body.Bytes(), &m)
			_, hasError := m["error"]
			assert.True(t, hasError)
		})
	}

	t.Run("wrong method returns 404", func(t *testing.T) {
		rr := doJSONRequest(t, r, http.MethodGet, "/statistics", "", "")
		assert.Equal(t, http.StatusNotFound, rr.Code)
	})
}

func TestContentTypeHeaderBehavior(t *testing.T) {
	r := setupRouter()
	// Valid JSON but wrong content-type; ShouldBindJSON should fail and handler returns 400.
	rr := doJSONRequest(t, r, http.MethodPost, "/parse", `{"content":"x","path":"a.go"}`, "text/plain")
	assert.Equal(t, http.StatusBadRequest, rr.Code)
}

func TestErrorResponseIsJSON(t *testing.T) {
	r := setupRouter()
	rr := doJSONRequest(t, r, http.MethodPost, "/parse", `{}`, "application/json")
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Header().Get("Content-Type"), "application/json")
	var m map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &m)
	assert.NoError(t, err)
	_, hasError := m["error"]
	assert.True(t, hasError)
}

func TestRoutesExist(t *testing.T) {
	r := setupRouter()
	type route struct {
		method string
		path   string
	}
	routes := []route{
		{http.MethodGet, "/health"},
		{http.MethodPost, "/parse"},
		{http.MethodPost, "/diff"},
		{http.MethodPost, "/metrics"},
		{http.MethodPost, "/statistics"},
	}
	for _, rt := range routes {
		var body bytes.Buffer
		rr := httptest.NewRecorder()
		req := httptest.NewRequest(rt.method, rt.path, &body)
		if rt.method == http.MethodPost {
			req.Header.Set("Content-Type", "application/json")
			req.Body = httptest.NewBody(`{}`)
		}
		r.ServeHTTP(rr, req)
		// Health should be 200. Others with empty body should be 400.
		if rt.path == "/health" {
			assert.Equal(t, http.StatusOK, rr.Code)
		} else {
			assert.Equal(t, http.StatusBadRequest, rr.Code)
		}
	}
}
