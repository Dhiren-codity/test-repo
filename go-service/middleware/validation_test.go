package middleware

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func clearValidationState(t *testing.T) {
	ClearValidationErrors()
}

func repeat(s string, n int) string {
	var b strings.Builder
	for i := 0; i < n; i++ {
		b.WriteString(s)
	}
	return b.String()
}

func containsErr(errs []ValidationError, field, reason string) bool {
	for _, e := range errs {
		if e.Field == field && e.Reason == reason {
			return true
		}
	}
	return false
}

func TestValidateParseRequest_ContentAndPathValidations(t *testing.T) {
	tests := []struct {
		name         string
		content      string
		path         string
		expectErrs   int
		expectChecks [][2]string
	}{
		{
			name:       "empty content",
			content:    "",
			path:       "valid/path.txt",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"content", "Content is required and cannot be empty"},
			},
		},
		{
			name:       "content too large",
			content:    repeat("a", MaxContentSize+1),
			path:       "valid/path.txt",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"content", "Content exceeds maximum size of 1MB"},
			},
		},
		{
			name:       "content with null bytes",
			content:    "abc\x00def",
			path:       "valid/path.txt",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"content", "Content contains invalid null bytes"},
			},
		},
		{
			name:       "path too long",
			content:    "ok",
			path:       repeat("a", MaxPathLength+1),
			expectErrs: 1,
			expectChecks: [][2]string{
				{"path", "Path exceeds maximum length"},
			},
		},
		{
			name:       "path directory traversal - dotdot",
			content:    "ok",
			path:       "../etc/passwd",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"path", "Path contains potential directory traversal"},
			},
		},
		{
			name:       "path directory traversal - tilde",
			content:    "ok",
			path:       "~/file",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"path", "Path contains potential directory traversal"},
			},
		},
		{
			name:         "valid content and path",
			content:      "hello world",
			path:         "folder/file.txt",
			expectErrs:   0,
			expectChecks: nil,
		},
		{
			name:       "multiple errors path length and traversal",
			content:    "ok",
			path:       "../" + repeat("a", MaxPathLength), // length will exceed and contains ..
			expectErrs: 2,
			expectChecks: [][2]string{
				{"path", "Path exceeds maximum length"},
				{"path", "Path contains potential directory traversal"},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			clearValidationState(t)
			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Len(t, errs, tt.expectErrs)

			globalErrs := GetValidationErrors()
			assert.Len(t, globalErrs, tt.expectErrs)

			for _, check := range tt.expectChecks {
				assert.True(t, containsErr(errs, check[0], check[1]))
				assert.True(t, containsErr(globalErrs, check[0], check[1]))
			}
		})
	}
}

func TestValidateDiffRequest_ErrorsAndNoErrors(t *testing.T) {
	tests := []struct {
		name         string
		oldContent   string
		newContent   string
		expectErrs   int
		expectChecks [][2]string
	}{
		{
			name:       "missing old content",
			oldContent: "",
			newContent: "new",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"old_content", "Old content is required"},
			},
		},
		{
			name:       "old content too large",
			oldContent: repeat("x", MaxContentSize+1),
			newContent: "new",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"old_content", "Old content exceeds maximum size"},
			},
		},
		{
			name:       "missing new content",
			oldContent: "old",
			newContent: "",
			expectErrs: 1,
			expectChecks: [][2]string{
				{"new_content", "New content is required"},
			},
		},
		{
			name:       "new content too large",
			oldContent: "old",
			newContent: repeat("y", MaxContentSize+1),
			expectErrs: 1,
			expectChecks: [][2]string{
				{"new_content", "New content exceeds maximum size"},
			},
		},
		{
			name:         "both valid",
			oldContent:   "old",
			newContent:   "new",
			expectErrs:   0,
			expectChecks: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			clearValidationState(t)
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			assert.Len(t, errs, tt.expectErrs)
			globalErrs := GetValidationErrors()
			assert.Len(t, globalErrs, tt.expectErrs)
			for _, check := range tt.expectChecks {
				assert.True(t, containsErr(errs, check[0], check[1]))
				assert.True(t, containsErr(globalErrs, check[0], check[1]))
			}
		})
	}
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	input := "Hello\x00World\x07!\n\r\t\x0b\x0c\x1f\x7f🙂"
	got := SanitizeInput(input)
	want := "HelloWorld!\n\r\t🙂"
	assert.Equal(t, want, got)
}

func TestSanitizeRequestBody_SanitizesKnownFields(t *testing.T) {
	raw := `{"content":"Hi\u0000 there\u0007","path":"..\u0000/abc","old_content":"old\u0000","new_content":"new\u0007"}`
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")

	SanitizeRequestBody(req)

	bodyBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	var m map[string]interface{}
	assert.NoError(t, json.Unmarshal(bodyBytes, &m))

	assert.Equal(t, "Hi there", m["content"])
	assert.Equal(t, "../abc", m["path"])
	assert.Equal(t, "old", m["old_content"])
	assert.Equal(t, "new", m["new_content"])
	assert.Equal(t, int64(len(bodyBytes)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSONLeavesBodyUntouched(t *testing.T) {
	raw := `{"content":` // invalid JSON
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(raw))
	SanitizeRequestBody(req)
	bodyBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, raw, string(bodyBytes))
}

func TestValidationMiddleware_POST_SanitizesBody(t *testing.T) {
	// content contains control char escaped in JSON to remain valid.
	raw := `{"content":"Hello\u0000World","path":"safe/path"}`
	req := httptest.NewRequest(http.MethodPost, "/parse", strings.NewReader(raw))
	rec := httptest.NewRecorder()

	var seen map[string]any
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		err = json.Unmarshal(data, &seen)
		assert.NoError(t, err)
		w.WriteHeader(http.StatusOK)
	})

	handler := ValidationMiddleware(next)
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "HelloWorld", seen["content"])
	assert.Equal(t, "safe/path", seen["path"])
}

func TestValidationMiddleware_NonPOST_PassesThroughUnmodified(t *testing.T) {
	raw := "not-json-and-should-pass-through"
	req := httptest.NewRequest(http.MethodGet, "/any", strings.NewReader(raw))
	rec := httptest.NewRecorder()

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, raw, string(b))
		w.WriteHeader(http.StatusTeapot)
	})
	handler := ValidationMiddleware(next)
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusTeapot, rec.Code)
}

func TestGetAndClearValidationErrors_CopyAndClear(t *testing.T) {
	clearValidationState(t)

	logValidationErrors([]ValidationError{
		{Field: "field1", Reason: "reason1"},
	})
	errs := GetValidationErrors()
	assert.Len(t, errs, 1)
	// mutate local copy
	errs[0].Field = "mutated"
	errs = append(errs, ValidationError{Field: "new", Reason: "new"})

	errs2 := GetValidationErrors()
	assert.Len(t, errs2, 1)
	assert.Equal(t, "field1", errs2[0].Field)

	ClearValidationErrors()
	assert.Len(t, GetValidationErrors(), 0)
}

func TestLogValidationErrors_TrimsToLast100(t *testing.T) {
	clearValidationState(t)

	for i := 0; i < 150; i++ {
		logValidationErrors([]ValidationError{
			{Field: fmt.Sprintf("f%d", i), Reason: "r"},
		})
	}
	errs := GetValidationErrors()
	assert.Len(t, errs, 100)
	assert.Equal(t, "f50", errs[0].Field)
	assert.Equal(t, "f149", errs[len(errs)-1].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}
