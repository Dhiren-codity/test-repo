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

func performRequest(t *testing.T, method, path, body string, contentType string, handler gin.HandlerFunc) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()

	switch method {
	case http.MethodGet:
		r.GET(path, handler)
	case http.MethodPost:
		r.POST(path, handler)
	case http.MethodPut:
		r.PUT(path, handler)
	case http.MethodDelete:
		r.DELETE(path, handler)
	default:
		r.Any(path, handler)
	}

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

func TestHealthCheck_OK(t *testing.T) {
	h := &Handler{}
	w := performRequest(t, http.MethodGet, "/health", "", "", h.HealthCheck)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")

	var resp map[string]any
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest_EmptyBody(t *testing.T) {
	h := &Handler{}
	w := performRequest(t, http.MethodPost, "/parse", "", "application/json", h.ParseFile)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/json")

	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestParseFile_BadRequest_MissingFields(t *testing.T) {
	h := &Handler{}
	body := `{}`

	w := performRequest(t, http.MethodPost, "/parse", body, "application/json", h.ParseFile)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestAnalyzeDiff_BadRequest_MissingFields(t *testing.T) {
	h := &Handler{}
	body := `{}`

	w := performRequest(t, http.MethodPost, "/diff", body, "application/json", h.AnalyzeDiff)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestAnalyzeDiff_BadRequest_InvalidJSON(t *testing.T) {
	h := &Handler{}
	body := `{` // malformed JSON

	w := performRequest(t, http.MethodPost, "/diff", body, "application/json", h.AnalyzeDiff)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestCalculateMetrics_BadRequest_MissingFields(t *testing.T) {
	h := &Handler{}
	body := `{}`

	w := performRequest(t, http.MethodPost, "/metrics", body, "application/json", h.CalculateMetrics)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestGetStatistics_BadRequest_MissingFiles(t *testing.T) {
	h := &Handler{}
	body := `{}`

	w := performRequest(t, http.MethodPost, "/statistics", body, "application/json", h.GetStatistics)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestGetStatistics_BadRequest_FilesEmptySlice(t *testing.T) {
	h := &Handler{}
	body := `{"files":[]}`

	w := performRequest(t, http.MethodPost, "/statistics", body, "application/json", h.GetStatistics)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}

func TestParseFile_BadRequest_WrongMethod(t *testing.T) {
	// Although the handler method itself doesn't enforce HTTP method,
	// this ensures the handler still returns a 400 for invalid/missing body under GET.
	h := &Handler{}
	w := performRequest(t, http.MethodGet, "/parse", "", "application/json", h.ParseFile)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var resp map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NotEmpty(t, resp["error"])
}
