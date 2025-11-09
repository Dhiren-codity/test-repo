package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
}

func setupRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	h := NewHandler()
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/health", h.HealthCheck)
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	return r
}

func performRequest(r http.Handler, method, path, body string) *httptest.ResponseRecorder {
	var reader *strings.Reader
	if body == "" {
		reader = strings.NewReader("")
	} else {
		reader = strings.NewReader(body)
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
	r := setupRouter()

	w := performRequest(r, http.MethodGet, "/health", "")

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	var got map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", got["status"])
	assert.Equal(t, "go-parser", got["service"])
}

func TestParseFile_BadRequest(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{name: "empty body", body: ``},
		{name: "invalid json", body: `{`},
		{name: "missing content", body: `{"path":"main.go"}`},
		{name: "missing path", body: `{"content":"package main\nfunc main(){}"}`},
		{name: "empty content string", body: `{"content":"","path":"main.go"}`}, // still considered provided but parser may fail; binding requires non-empty, so 400
		{name: "empty path string", body: `{"content":"x","path":""}`},          // binding requires non-empty, so 400
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(r, http.MethodPost, "/parse", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestParseFile_OK(t *testing.T) {
	r := setupRouter()
	body := `{"content":"package main\nfunc main(){}\n","path":"main.go"}`
	w := performRequest(r, http.MethodPost, "/parse", body)

	assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	assert.NotContains(t, w.Body.String(), `"error"`)
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{name: "empty body", body: ``},
		{name: "invalid json", body: `{`},
		{name: "missing old_content", body: `{"new_content":"package main\nfunc main(){}\n"}`},
		{name: "missing new_content", body: `{"old_content":"package main\nfunc main(){}\n"}`},
		{name: "empty fields", body: `{"old_content":"","new_content":""}`}, // required non-empty
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(r, http.MethodPost, "/diff", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestAnalyzeDiff_OK(t *testing.T) {
	r := setupRouter()
	oldContent := "package main\nfunc main(){println(\"old\")}\n"
	newContent := "package main\nfunc main(){println(\"new\")}\n"
	body := `{"old_content":` + jsonString(oldContent) + `,"new_content":` + jsonString(newContent) + `}`
	w := performRequest(r, http.MethodPost, "/diff", body)

	assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	assert.NotContains(t, w.Body.String(), `"error"`)
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{name: "empty body", body: ``},
		{name: "invalid json", body: `{`},
		{name: "missing content", body: `{}`},
		{name: "empty content", body: `{"content":""}`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(r, http.MethodPost, "/metrics", tt.body)
			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestCalculateMetrics_OK(t *testing.T) {
	r := setupRouter()
	body := `{"content":"package main\n// comment\nfunc main(){println(\"hi\")}\n"}`
	w := performRequest(r, http.MethodPost, "/metrics", body)

	assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	assert.NotContains(t, w.Body.String(), `"error"`)
}

func TestGetStatistics_BadRequest(t *testing.T) {
	r := setupRouter()
	tests := []struct {
		name string
		body string
	}{
		{name: "empty body", body: ``},
		{name: "invalid json", body: `{`},
		{name: "missing files", body: `{}`},
		{name: "files wrong type", body: `{"files":{}}`},
		{name: "file missing content", body: `{"files":[{"path":"main.go"}]}`},
		{name: "file missing path", body: `{"files":[{"content":"package main\nfunc main(){}\n"}]}`},
		{name: "file empty content", body: `{"files":[{"content":"","path":"main.go"}]}`},
		{name: "file empty path", body: `{"files":[{"content":"x","path":""}]}`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := performRequest(r, http.MethodPost, "/statistics", tt.body)

			// Behavior per source:
			// - empty/malformed/missing files => 400
			// - missing or empty path => parser error => 500
			// - missing or empty content => accepted by parser => 200
			switch tt.name {
			case "file missing path", "file empty path":
				assert.Equal(t, http.StatusInternalServerError, w.Code)
				return
			case "file missing content", "file empty content":
				assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
				assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
				assert.NotContains(t, w.Body.String(), `"error"`)
				return
			}

			assert.Equal(t, http.StatusBadRequest, w.Code)
			assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
			assert.Contains(t, w.Body.String(), "error")
		})
	}
}

func TestGetStatistics_OK(t *testing.T) {
	r := setupRouter()
	file := map[string]string{
		"content": "package main\nfunc main(){}\n",
		"path":    "main.go",
	}
	payload := map[string]any{
		"files": []map[string]string{file},
	}
	b, _ := json.Marshal(payload)

	w := performRequest(r, http.MethodPost, "/statistics", string(b))

	assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	assert.NotContains(t, w.Body.String(), `"error"`)
}

// jsonString safely quotes a raw string for embedding into JSON literal construction.
func jsonString(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}