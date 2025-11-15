package middleware

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestSanitizeRequestBody_JSONSanitization(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	payload := `{
		"content":"Hi\u0000 there",
		"path":"some\u000Bpath",
		"old_content":"old\u0001",
		"new_content":"new\u0002",
		"other":123
	}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(payload))

	SanitizeRequestBody(req)

	bodyBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(bodyBytes)), req.ContentLength)

	var m map[string]any
	err = json.Unmarshal(bodyBytes, &m)
	assert.NoError(t, err)
	assert.Equal(t, "Hi there", m["content"])
	assert.Equal(t, "somepath", m["path"])
	assert.Equal(t, "old", m["old_content"])
	assert.Equal(t, "new", m["new_content"])
	assert.Equal(t, float64(123), m["other"])
}

func TestSanitizeRequestBody_InvalidJSONLeavesBodyUnchanged(t *testing.T) {
	orig := "not a json"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	SanitizeRequestBody(req)

	bodyBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(bodyBytes))
}

func TestValidationMiddleware_POSTSanitizesJSON(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var m map[string]string
		_ = json.NewDecoder(r.Body).Decode(&m)
		_ = json.NewEncoder(w).Encode(m)
	})

	handler := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(`{"content":"Hi\u0000 there","path":"some\u000Bpath"}`))
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	var got map[string]string
	err := json.Unmarshal(rr.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "Hi there", got["content"])
	assert.Equal(t, "somepath", got["path"])
}

func TestValidationMiddleware_POSTInvalidJSONPassesThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Echo raw body back
		b, _ := io.ReadAll(r.Body)
		_, _ = w.Write(b)
	})

	handler := ValidationMiddleware(next)

	orig := "invalid json"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, orig, rr.Body.String())
}

func TestValidationMiddleware_GETPassThrough(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Decode JSON and echo it back
		var m map[string]string
		_ = json.NewDecoder(r.Body).Decode(&m)
		_ = json.NewEncoder(w).Encode(m)
	})

	handler := ValidationMiddleware(next)

	// Middleware should not sanitize on GET
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(`{"content":"Hi\u0000 there","path":"some\u000Bpath"}`))
	rr := httptest.NewRecorder()

	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	var got map[string]string
	err := json.Unmarshal(rr.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "Hi\x00 there", got["content"])
	assert.Equal(t, "some\x0Bpath", got["path"])
}

func TestValidateParseRequest_Table(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	tests := []struct {
		name        string
		content     string
		path        string
		wantFields  []string
		wantReasons []string
	}{
		{
			name:       "empty content",
			content:    "",
			path:       "ok/path",
			wantFields: []string{"content"},
			wantReasons: []string{
				"Content is required and cannot be empty",
			},
		},
		{
			name:       "path too long",
			content:    "abc",
			path:       strings.Repeat("a", MaxPathLength+1),
			wantFields: []string{"path"},
			wantReasons: []string{
				"Path exceeds maximum length",
			},
		},
		{
			name:       "content null bytes",
			content:    "a\u0000b",
			path:       "valid",
			wantFields: []string{"content"},
			wantReasons: []string{
				"Content contains invalid null bytes",
			},
		},
		{
			name:       "content exceeds size",
			content:    strings.Repeat("x", MaxContentSize+1),
			path:       "valid",
			wantFields: []string{"content"},
			wantReasons: []string{
				"Content exceeds maximum size of 1MB",
			},
		},
		{
			name:       "path traversal",
			content:    "ok",
			path:       "../etc/passwd",
			wantFields: []string{"path"},
			wantReasons: []string{
				"Path contains potential directory traversal",
			},
		},
		{
			name:       "path home traversal",
			content:    "ok",
			path:       "~/secrets",
			wantFields: []string{"path"},
			wantReasons: []string{
				"Path contains potential directory traversal",
			},
		},
		{
			name:    "multiple path issues both reported",
			content: "ok",
			path:    strings.Repeat("a", MaxPathLength+1) + "../x",
			wantFields: []string{
				"path", "path",
			},
			wantReasons: []string{
				"Path exceeds maximum length",
				"Path contains potential directory traversal",
			},
		},
		{
			name:       "valid content and path no errors",
			content:    "ok",
			path:       "valid/path",
			wantFields: nil,
		},
		{
			name:       "content too long with null bytes only size error due to else-if",
			content:    strings.Repeat("x", MaxContentSize+1) + "\u0000",
			path:       "valid",
			wantFields: []string{"content"},
			wantReasons: []string{
				"Old content exceeds maximum size", // not applicable here; fix below
			},
		},
	}

	// Fix the incorrect expected reason for the size test above
	tests[8].wantReasons = []string{"Content exceeds maximum size of 1MB"}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, tt.path)
			if len(tt.wantFields) == 0 {
				assert.Empty(t, errs)
				assert.Empty(t, GetValidationErrors())
				return
			}
			assert.Len(t, errs, len(tt.wantFields))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				if i < len(tt.wantReasons) {
					assert.Equal(t, tt.wantReasons[i], e.Reason)
				}
				assert.WithinDuration(t, time.Now(), e.Time, time.Second)
			}
			// Logged as well
			logged := GetValidationErrors()
			assert.Len(t, logged, len(errs))
		})
	}
}

func TestValidateDiffRequest_Table(t *testing.T) {
	t.Cleanup(ClearValidationErrors)

	tests := []struct {
		name        string
		oldContent  string
		newContent  string
		wantFields  []string
		wantReasons []string
	}{
		{
			name:        "both empty",
			oldContent:  "",
			newContent:  "",
			wantFields:  []string{"old_content", "new_content"},
			wantReasons: []string{"Old content is required", "New content is required"},
		},
		{
			name:        "old too big",
			oldContent:  strings.Repeat("a", MaxContentSize+1),
			newContent:  "ok",
			wantFields:  []string{"old_content"},
			wantReasons: []string{"Old content exceeds maximum size"},
		},
		{
			name:        "new too big",
			oldContent:  "ok",
			newContent:  strings.Repeat("b", MaxContentSize+1),
			wantFields:  []string{"new_content"},
			wantReasons: []string{"New content exceeds maximum size"},
		},
		{
			name:       "both ok",
			oldContent: "old",
			newContent: "new",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			if len(tt.wantFields) == 0 {
				assert.Empty(t, errs)
				assert.Empty(t, GetValidationErrors())
				return
			}
			assert.Len(t, errs, len(tt.wantFields))
			for i, e := range errs {
				assert.Equal(t, tt.wantFields[i], e.Field)
				assert.Equal(t, tt.wantReasons[i], e.Reason)
				assert.WithinDuration(t, time.Now(), e.Time, time.Second)
			}
			// Logged as well
			logged := GetValidationErrors()
			assert.Len(t, logged, len(errs))
		})
	}
}

func TestGetAndClearValidationErrors_CopySemantics(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "a", Reason: "ra", Time: now},
		{Field: "b", Reason: "rb", Time: now},
	})

	got := GetValidationErrors()
	assert.Len(t, got, 2)

	// Mutate returned slice
	got[0].Field = "mutated"
	// Ensure underlying store unchanged
	got2 := GetValidationErrors()
	assert.Equal(t, "a", got2[0].Field)

	// Clear works
	ClearValidationErrors()
	got3 := GetValidationErrors()
	assert.Empty(t, got3)
}

func TestLogValidationErrors_TrimTo100(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	for i := 0; i < 130; i++ {
		e := ValidationError{
			Field:  fmt.Sprintf("f%d", i),
			Reason: "r",
			Time:   time.Now(),
		}
		logValidationErrors([]ValidationError{e})
	}

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "f30", got[0].Field)
	assert.Equal(t, "f129", got[99].Field)

	// No-op on empty input
	logValidationErrors(nil)
	got2 := GetValidationErrors()
	assert.Len(t, got2, 100)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}
