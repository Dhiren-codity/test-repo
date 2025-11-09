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

func setupRouter() (*gin.Engine, *Handler) {
	gin.SetMode(gin.TestMode)
	h := NewHandler()
	r := gin.New()
	r.POST("/parse", h.ParseFile)
	r.POST("/diff", h.AnalyzeDiff)
	r.POST("/metrics", h.CalculateMetrics)
	r.POST("/statistics", h.GetStatistics)
	r.GET("/health", h.HealthCheck)
	return r, h
}

func TestHealthCheck_OK(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	var body map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &body)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", body["status"])
	assert.Equal(t, "go-parser", body["service"])
}

func TestHealthCheck_WrongMethod(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/health", nil)
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusNotFound, w.Code)
}

func TestParseFile_BadJSON(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader("{bad"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	assert.Contains(t, body["error"], "invalid character")
}

func TestParseFile_MissingFields(t *testing.T) {
	r, _ := setupRouter()
	tests := []struct {
		name       string
		payload    string
		wantErrSub string
	}{
		{
			name:       "missing content",
			payload:    `{"path":"file.go"}`,
			wantErrSub: "Content",
		},
		{
			name:       "missing path",
			payload:    `{"content":"code"}`,
			wantErrSub: "Path",
		},
		{
			name:       "empty body",
			payload:    ``,
			wantErrSub: "EOF",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var bodyReader *strings.Reader
			bodyReader = strings.NewReader(tt.payload)
			req := httptest.NewRequest(http.MethodPost, "/parse", bodyReader)
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var body map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &body)
			errStr, _ := body["error"].(string)
			assert.NotEmpty(t, errStr)
			assert.Contains(t, errStr, tt.wantErrSub)
		})
	}
}

func TestAnalyzeDiff_BadJSON(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader("{bad"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	assert.Contains(t, body["error"], "invalid character")
}

func TestAnalyzeDiff_MissingFields(t *testing.T) {
	r, _ := setupRouter()
	tests := []struct {
		name       string
		payload    string
		wantErrSub string
	}{
		{
			name:       "missing old_content",
			payload:    `{"new_content":"n"}`,
			wantErrSub: "OldContent",
		},
		{
			name:       "missing new_content",
			payload:    `{"old_content":"o"}`,
			wantErrSub: "NewContent",
		},
		{
			name:       "empty body",
			payload:    ``,
			wantErrSub: "EOF",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/diff", strings.NewReader(tt.payload))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var body map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &body)
			errStr, _ := body["error"].(string)
			assert.NotEmpty(t, errStr)
			assert.Contains(t, errStr, tt.wantErrSub)
		})
	}
}

func TestCalculateMetrics_BadJSON(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader("{bad"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	assert.Contains(t, body["error"], "invalid character")
}

func TestCalculateMetrics_MissingContent(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/metrics", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	errStr, _ := body["error"].(string)
	assert.Contains(t, errStr, "Content")
}

func TestGetStatistics_BadJSON(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader("{bad"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	assert.Contains(t, body["error"], "invalid character")
}

func TestGetStatistics_MissingFilesField(t *testing.T) {
	r, _ := setupRouter()
	req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	errStr, _ := body["error"].(string)
	assert.Contains(t, errStr, "Files")
}

func TestGetStatistics_FileItemMissingFields(t *testing.T) {
	r, _ := setupRouter()
	tests := []struct {
		name       string
		payload    string
		wantErrSub string
	}{
		{
			name:       "file missing content",
			payload:    `{"files":[{"path":"a.go"}]}`,
			wantErrSub: "Content",
		},
		{
			name:       "file missing path",
			payload:    `{"files":[{"content":"code"}]}`,
			wantErrSub: "Path",
		},
		{
			name:       "empty files array allowed? still passes validation of 'required' tag on nested fields triggers 400",
			payload:    `{"files":[{}]}`,
			wantErrSub: "Content",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/statistics", strings.NewReader(tt.payload))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()

			r.ServeHTTP(w, req)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var body map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &body)
			errStr, _ := body["error"].(string)
			assert.Contains(t, errStr, tt.wantErrSub)
		})
	}
}

func TestRoutes_MethodsAndNotFound(t *testing.T) {
	r, _ := setupRouter()

	// GET on POST-only route -> 404
	req1 := httptest.NewRequest(http.MethodGet, "/parse", nil)
	w1 := httptest.NewRecorder()
	r.ServeHTTP(w1, req1)
	assert.Equal(t, http.StatusNotFound, w1.Code)

	// GET on POST-only route -> 404
	req2 := httptest.NewRequest(http.MethodGet, "/statistics", nil)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	assert.Equal(t, http.StatusNotFound, w2.Code)

	// Unknown route -> 404
	req3 := httptest.NewRequest(http.MethodDelete, "/unknown", nil)
	w3 := httptest.NewRecorder()
	r.ServeHTTP(w3, req3)
	assert.Equal(t, http.StatusNotFound, w3.Code)
}

func TestErrorResponses_AreJSON(t *testing.T) {
	r, _ := setupRouter()
	// Trigger 400 by sending empty JSON for required fields
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	ct := w.Header().Get("Content-Type")
	assert.Contains(t, ct, "application/json")
	var body map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &body)
	assert.NoError(t, err)
	_, ok := body["error"]
	assert.True(t, ok)
}
