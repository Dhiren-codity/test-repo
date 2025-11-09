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
