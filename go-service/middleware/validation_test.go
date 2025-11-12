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

func TestValidateParseRequest(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name        string
		content     string
		path        string
		wantErrs    int
		wantFields  []string
		wantReasons []string
	}{
		{
			name:     "valid",
			content:  "hello world",
			path:     "dir/file.txt",
			wantErrs: 0,
		},
		{
			name:        "empty content",
			content:     "",
			path:        "file.txt",
			wantErrs:    1,
			wantFields:  []string{"content"},
			wantReasons: []string{"Content is required"},
		},
		{
			name:        "oversize content",
			content:     strings.Repeat("a", MaxContentSize+1),
			path:        "file.txt",
			wantErrs:    1,
			wantFields:  []string{"content"},
			wantReasons: []string{"exceeds"},
		},
		{
			name:        "content with null byte",
			content:     "abc\x00def",
			path:        "file.txt",
			wantErrs:    1,
			wantFields:  []string{"content"},
			wantReasons: []string{"invalid null bytes"},
		},
		{
			name:        "path too long",
			content:     "hello",
			path:        strings.Repeat("p", MaxPathLength+1),
			wantErrs:    1,
			wantFields:  []string{"path"},
			wantReasons: []string{"maximum length"},
		},
		{
			name:        "path traversal dotdot",
			content:     "hello",
			path:        "../etc/passwd",
			wantErrs:    1,
			wantFields:  []string{"path"},
			wantReasons: []string{"directory traversal"},
		},
		{
			name:        "path traversal tilde",
			content:     "hello",
			path:        "~/data",
			wantErrs:    1,
			wantFields:  []string{"path"},
			wantReasons: []string{"directory traversal"},
		},
		{
			name:        "multiple errors content and path length and traversal",
			content:     "",
			path:        strings.Repeat(".", MaxPathLength+10) + "../x",
			wantErrs:    2, // content empty + path traversal (length and traversal both possible, but traversal is one error and length another -> total 2 or 3? With the given path, length > MaxPathLength and contains "..", so 2 path errors + 1 content => 3
			wantFields:  []string{"content", "path"},
			wantReasons: []string{"Content is required", "Path contains"},
		},
	}

	for _, tt := range tests {
		ClearValidationErrors()
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			if tt.name == "multiple errors content and path length and traversal" {
				// Adjust expected count to 3 for this specific case
				assert.Equal(t, 3, len(errs))
			} else {
				assert.Equal(t, tt.wantErrs, len(errs))
			}
			for i, f := range tt.wantFields {
				found := false
				for _, e := range errs {
					if e.Field == f {
						found = true
						break
					}
				}
				assert.True(t, found, "expected field error for %s", f)
				if i < len(tt.wantReasons) {
					reasonSub := tt.wantReasons[i]
					foundReason := false
					for _, e := range errs {
						if strings.Contains(e.Reason, reasonSub) {
							foundReason = true
							break
						}
					}
					assert.True(t, foundReason, "expected reason containing %q", reasonSub)
				}
			}
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	ClearValidationErrors()

	tests := []struct {
		name        string
		oldContent  string
		newContent  string
		wantErrs    int
		wantFields  []string
		wantReasons []string
	}{
		{
			name:       "valid diff",
			oldContent: "old text",
			newContent: "new text",
			wantErrs:   0,
		},
		{
			name:        "missing old content",
			oldContent:  "",
			newContent:  "new text",
			wantErrs:    1,
			wantFields:  []string{"old_content"},
			wantReasons: []string{"required"},
		},
		{
			name:        "missing new content",
			oldContent:  "old text",
			newContent:  "",
			wantErrs:    1,
			wantFields:  []string{"new_content"},
			wantReasons: []string{"required"},
		},
		{
			name:        "both missing",
			oldContent:  "",
			newContent:  "",
			wantErrs:    2,
			wantFields:  []string{"old_content", "new_content"},
			wantReasons: []string{"required", "required"},
		},
		{
			name:        "oversize old content",
			oldContent:  strings.Repeat("x", MaxContentSize+1),
			newContent:  "new",
			wantErrs:    1,
			wantFields:  []string{"old_content"},
			wantReasons: []string{"exceeds"},
		},
		{
			name:        "oversize new content",
			oldContent:  "old",
			newContent:  strings.Repeat("x", MaxContentSize+1),
			wantErrs:    1,
			wantFields:  []string{"new_content"},
			wantReasons: []string{"exceeds"},
		},
	}

	for _, tt := range tests {
		ClearValidationErrors()
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			assert.Equal(t, tt.wantErrs, len(errs))
			for i, f := range tt.wantFields {
				found := false
				for _, e := range errs {
					if e.Field == f {
						found = true
						break
					}
				}
				assert.True(t, found, "expected field error for %s", f)
				if i < len(tt.wantReasons) {
					reasonSub := tt.wantReasons[i]
					foundReason := false
					for _, e := range errs {
						if strings.Contains(e.Reason, reasonSub) {
							foundReason = true
							break
						}
					}
					assert.True(t, foundReason, "expected reason containing %q", reasonSub)
				}
			}
		})
	}
}

func TestSanitizeInput_RemovesControlCharsExceptAllowed(t *testing.T) {
	in := "A\x00B\x01C\nD\tE\rF\x0B\x0C\x0E\x7F"
	out := SanitizeInput(in)
	assert.Equal(t, "ABC\nD\tE\rF", out)
}

func TestSanitizeRequestBody_SanitizesKnownFields(t *testing.T) {
	body := map[string]interface{}{
		"content":      "he\x00llo",
		"path":         "\x01p/a\tn",
		"old_content":  "old\x0B",
		"new_content":  "new\x7F",
		"unknown":      "keep\x02",
		"anotherField": 123,
	}
	b, _ := json.Marshal(body)
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(b))

	SanitizeRequestBody(r)

	// Read back the sanitized body
	gotBytes, err := io.ReadAll(r.Body)
	assert.NoError(t, err)

	var got map[string]interface{}
	err = json.Unmarshal(gotBytes, &got)
	assert.NoError(t, err)

	assert.Equal(t, "hello", got["content"])
	assert.Equal(t, "p/a\tn", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])
	// unknown field remains unchanged (only specific fields are sanitized)
	assert.Equal(t, "keep\x02", got["unknown"])
	assert.Equal(t, float64(123), got["anotherField"])

	assert.Equal(t, int64(len(gotBytes)), r.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSONPreservesBody(t *testing.T) {
	orig := "not-json"
	r := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	SanitizeRequestBody(r)

	got, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(got))
}

func TestValidationMiddleware_SanitizesPostBody(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)

		// Echo back the body to inspect what middleware produced
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(b)

		var m map[string]interface{}
		_ = json.Unmarshal(b, &m)
		// Ensure content/path sanitized
		assert.Equal(t, "ab", m["content"])
		assert.Equal(t, "home", m["path"])
		// Ensure ContentLength reflects sanitized body size
		assert.Equal(t, int64(len(b)), r.ContentLength)
	})

	mw := ValidationMiddleware(handler)

	reqBody := `{"content":"a\u0000b","path":"h\u0001ome"}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(reqBody))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Result().StatusCode)

	var got map[string]interface{}
	_ = json.Unmarshal(rr.Body.Bytes(), &got)
	assert.Equal(t, "ab", got["content"])
	assert.Equal(t, "home", got["path"])
}

func TestValidationMiddleware_NonPostPassthrough(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})
	mw := ValidationMiddleware(handler)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Result().StatusCode)
	assert.Equal(t, "ok", rr.Body.String())
}

type errReadCloser struct{}

func (e errReadCloser) Read(p []byte) (int, error) { return 0, fmt.Errorf("read error") }
func (e errReadCloser) Close() error               { return nil }

func TestValidationMiddleware_BodyReadError(t *testing.T) {
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// should not be reached
		w.WriteHeader(http.StatusTeapot)
	})
	mw := ValidationMiddleware(handler)

	req := httptest.NewRequest(http.MethodPost, "/", io.NopCloser(errReadCloser{}))
	rr := httptest.NewRecorder()

	mw.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusBadRequest, rr.Result().StatusCode)
	assert.Contains(t, rr.Body.String(), "Failed to read request body")
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())

	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "content", Reason: "Content is required", Time: now},
	})
	got := GetValidationErrors()
	assert.Len(t, got, 1)
	assert.Equal(t, "content", got[0].Field)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestLogValidationErrors_CappedTo100(t *testing.T) {
	ClearValidationErrors()

	// Add 120 single-entry logs so that the storage is capped to last 100
	for i := 0; i < 120; i++ {
		logValidationErrors([]ValidationError{
			{
				Field:  fmt.Sprintf("f%03d", i),
				Reason: "test",
				Time:   time.Now(),
			},
		})
	}

	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "f020", got[0].Field) // should keep from 20..119
	assert.Equal(t, "f119", got[99].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}
