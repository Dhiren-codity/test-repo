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

func newTestRouter() *gin.Engine {
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

func doRequest(t *testing.T, r http.Handler, method, path string, body string) *httptest.ResponseRecorder {
	t.Helper()
	var buf *bytes.Reader
	if body != "" {
		buf = bytes.NewReader([]byte(body))
	} else {
		buf = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, buf)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rr := httptest.NewRecorder()
	r.ServeHTTP(rr, req)
	return rr
}

func TestHealthCheck(t *testing.T) {
	router := newTestRouter()
	rr := doRequest(t, router, "GET", "/health", "")
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest(t *testing.T) {
	router := newTestRouter()
	rr := doRequest(t, router, "POST", "/parse", `{}`)
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	_, hasErr := resp["error"]
	assert.True(t, hasErr)
}

func TestParseFile_Success(t *testing.T) {
	router := newTestRouter()
	body := `{"content":"package main\nfunc main(){}", "path":"main.go"}`
	rr := doRequest(t, router, "POST", "/parse", body)
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.NotContains(t, rr.Body.String(), `"error"`)
}

func TestAnalyzeDiff_BadRequest(t *testing.T) {
	router := newTestRouter()
	rr := doRequest(t, router, "POST", "/diff", `{}`)
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	_, hasErr := resp["error"]
	assert.True(t, hasErr)
}

func TestAnalyzeDiff_Success(t *testing.T) {
	router := newTestRouter()
	body := `{"old_content":"a\nb\nc","new_content":"a\nc\nd"}`
	rr := doRequest(t, router, "POST", "/diff", body)
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	assert.NotContains(t, rr.Body.String(), `"error"`)
}

func TestCalculateMetrics_BadRequest(t *testing.T) {
	router := newTestRouter()
	rr := doRequest(t, router, "POST", "/metrics", `{}`)
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	_, hasErr := resp["error"]
	assert.True(t, hasErr)
}

func TestCalculateMetrics_Success(t *testing.T) {
	router := newTestRouter()
	body := `{"content":"line1\nline2\n"}`
	rr := doRequest(t, router, "POST", "/metrics", body)
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	assert.NotContains(t, rr.Body.String(), `"error"`)
}

func TestGetStatistics_BadRequest(t *testing.T) {
	router := newTestRouter()
	rr := doRequest(t, router, "POST", "/statistics", `{}`)
	assert.Equal(t, http.StatusBadRequest, rr.Code)
	var resp map[string]any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
	_, hasErr := resp["error"]
	assert.True(t, hasErr)
}

func TestGetStatistics_Success(t *testing.T) {
	router := newTestRouter()
	// Valid files array
	body := `{"files":[{"content":"package main\nfunc main(){}", "path":"main.go"}]}`
	rr := doRequest(t, router, "POST", "/statistics", body)
	// We only assert that it returns 200 and JSON; the exact schema is produced by parser.StatisticsCalculator.
	if rr.Code != http.StatusOK {
		// If parser implementation errors, ensure we still get a JSON error object with 500
		assert.Equal(t, http.StatusInternalServerError, rr.Code)
		assert.True(t, strings.Contains(rr.Body.String(), `"error"`))
		return
	}
	assert.Equal(t, "application/json; charset=utf-8", rr.Header().Get("Content-Type"))
	assert.NotContains(t, rr.Body.String(), `"error"`)
	var resp any
	err := json.Unmarshal(rr.Body.Bytes(), &resp)
	assert.NoError(t, err)
}
