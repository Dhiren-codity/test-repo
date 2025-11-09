package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func init() {
	gin.SetMode(gin.TestMode)
}

func newJSONRequest(method, target string, body string) (*gin.Context, *httptest.ResponseRecorder) {
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	req := httptest.NewRequest(method, target, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	c.Request = req
	return c, w
}

func TestHealthCheck_OK(t *testing.T) {
	h := NewHandler()

	c, w := newJSONRequest("GET", "/health", "")
	h.HealthCheck(c)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]string
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "healthy", resp["status"])
	assert.Equal(t, "go-parser", resp["service"])
}

func TestParseFile_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()

	tests := []struct {
		name string
		body string
	}{
		{name: "empty body", body: ``},
		{name: "empty json object", body: `{}`},
		{name: "missing path", body: `{"content":"code"}`},
		{name: "missing content", body: `{"path":"main.go"}`},
		{name: "bad json", body: `{"content":`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, w := newJSONRequest("POST", "/parse", tt.body)
			h.ParseFile(c)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestAnalyzeDiff_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()

	tests := []struct {
		name string
		body string
	}{
		{name: "empty json", body: `{}`},
		{name: "missing old_content", body: `{"new_content":"bar"}`},
		{name: "missing new_content", body: `{"old_content":"foo"}`},
		{name: "bad json", body: `{"old_content":`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, w := newJSONRequest("POST", "/diff", tt.body)
			h.AnalyzeDiff(c)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestCalculateMetrics_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()

	tests := []struct {
		name string
		body string
	}{
		{name: "empty json", body: `{}`},
		{name: "missing content", body: `{"foo":"bar"}`},
		{name: "bad json", body: `{"content":`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, w := newJSONRequest("POST", "/metrics", tt.body)
			h.CalculateMetrics(c)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}

func TestGetStatistics_BadRequest_MissingFields(t *testing.T) {
	h := NewHandler()

	tests := []struct {
		name string
		body string
	}{
		{name: "empty json", body: `{}`},
		{name: "missing files", body: `{"foo":"bar"}`},
		{name: "files present but empty objects", body: `{"files":[{}]}`},
		{name: "bad json", body: `{"files":`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, w := newJSONRequest("POST", "/statistics", tt.body)
			h.GetStatistics(c)

			assert.Equal(t, http.StatusBadRequest, w.Code)
			var resp map[string]any
			_ = json.Unmarshal(w.Body.Bytes(), &resp)
			_, hasErr := resp["error"]
			assert.True(t, hasErr, "expected error field in response")
		})
	}
}
