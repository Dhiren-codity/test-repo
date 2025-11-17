package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest_ContentValidation(t *testing.T) {
	tests := []struct {
		name        string
		content     string
		expectedFld string
		expectedRsn string
	}{
		{
			name:        "empty content",
			content:     "",
			expectedFld: "content",
			expectedRsn: "Content is required and cannot be empty",
		},
		{
			name:        "too large content",
			content:     strings.Repeat("a", MaxContentSize+1),
			expectedFld: "content",
			expectedRsn: "Content exceeds maximum size of 1MB",
		},
		{
			name:        "content with null bytes",
			content:     "abc\x00def",
			expectedFld: "content",
			expectedRsn: "Content contains invalid null bytes",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, "")
			assert.Len(t, errs, 1)
			assert.Equal(t, tt.expectedFld, errs[0].Field)
			assert.Equal(t, tt.expectedRsn, errs[0].Reason)

			logged := GetValidationErrors()
			assert.Len(t, logged, 1)
			assert.Equal(t, tt.expectedFld, logged[0].Field)
			assert.Equal(t, tt.expectedRsn, logged[0].Reason)
		})
	}
}

func TestValidateParseRequest_PathValidation(t *testing.T) {
	tests := []struct {
		name        string
		path        string
		expectedFld string
		expectedRsn string
	}{
		{
			name:        "path too long",
			path:        strings.Repeat("x", MaxPathLength+1),
			expectedFld: "path",
			expectedRsn: "Path exceeds maximum length",
		},
		{
			name:        "path traversal double dot",
			path:        "/var/../etc/passwd",
			expectedFld: "path",
			expectedRsn: "Path contains potential directory traversal",
		},
		{
			name:        "path traversal tilde",
			path:        "~/secrets",
			expectedFld: "path",
			expectedRsn: "Path contains potential directory traversal",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest("ok", tt.path)
			assert.Len(t, errs, 1)
			assert.Equal(t, tt.expectedFld, errs[0].Field)
			assert.Equal(t, tt.expectedRsn, errs[0].Reason)

			logged := GetValidationErrors()
			assert.Len(t, logged, 1)
			assert.Equal(t, tt.expectedFld, logged[0].Field)
			assert.Equal(t, tt.expectedRsn, logged[0].Reason)
		})
	}
}

func TestValidateParseRequest_LoggingCappedAt100(t *testing.T) {
	ClearValidationErrors()
	for i := 0; i < 105; i++ {
		_ = ValidateParseRequest("", "")
	}
	logged := GetValidationErrors()
	assert.Len(t, logged, 100)
	for _, e := range logged {
		assert.Equal(t, "content", e.Field)
		assert.Equal(t, "Content is required and cannot be empty", e.Reason)
	}
}

func TestValidateDiffRequest_ValidNoErrors(t *testing.T) {
	ClearValidationErrors()
	errs := ValidateDiffRequest("old", "new")
	assert.Empty(t, errs)
	logged := GetValidationErrors()
	assert.Empty(t, logged)
}

func TestValidateDiffRequest_Errors(t *testing.T) {
	tests := []struct {
		name          string
		oldContent    string
		newContent    string
		expectedCount int
		expectedPairs map[string]string
	}{
		{
			name:          "both empty",
			oldContent:    "",
			newContent:    "",
			expectedCount: 2,
			expectedPairs: map[string]string{
				"old_content": "Old content is required",
				"new_content": "New content is required",
			},
		},
		{
			name:          "old too big",
			oldContent:    strings.Repeat("o", MaxContentSize+1),
			newContent:    "new",
			expectedCount: 1,
			expectedPairs: map[string]string{
				"old_content": "Old content exceeds maximum size",
			},
		},
		{
			name:          "new too big",
			oldContent:    "old",
			newContent:    strings.Repeat("n", MaxContentSize+1),
			expectedCount: 1,
			expectedPairs: map[string]string{
				"new_content": "New content exceeds maximum size",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			assert.Len(t, errs, tt.expectedCount)
			for _, e := range errs {
				assert.Equal(t, tt.expectedPairs[e.Field], e.Reason)
			}
			logged := GetValidationErrors()
			assert.Len(t, logged, tt.expectedCount)
		})
	}
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	// Includes: null (\x00), bell(\x07), newline(\n), tab(\t), carriage return(\r),
	// vertical tab(\x0b), form feed(\x0c), shift out(\x0e), DEL(\x7f)
	in := "A\x00B\x07C\nD\tE\rF\x0b\x0c\x0eG\x7F"
	out := SanitizeInput(in)
	assert.Equal(t, "ABC\nD\tE\rFG", out)
}

func TestSanitizeRequestBody_JSON_SanitizesFieldsAndSetsContentLength(t *testing.T) {
	payload := map[string]interface{}{
		"content":     "A\x00B",
		"path":        "P\x0bQ",
		"old_content": "O\x1fL",
		"new_content": "N\x7fW",
		"other":       "X\x00Y", // not sanitized by function
	}
	body, err := json.Marshal(payload)
	assert.NoError(t, err)

	req := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewReader(body))
	SanitizeRequestBody(req)

	sanitizedBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(sanitizedBytes)), req.ContentLength)

	var got map[string]string
	err = json.Unmarshal(sanitizedBytes, &got)
	assert.NoError(t, err)

	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "PQ", got["path"])
	assert.Equal(t, "OL", got["old_content"])
	assert.Equal(t, "NW", got["new_content"])
	// Ensure "other" remained unsanitized; it should still contain the control char (escaped in JSON)
	assert.Equal(t, "X\x00Y", got["other"])
}

func TestSanitizeRequestBody_InvalidJSON_NoChange(t *testing.T) {
	orig := []byte("not json")
	req := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewReader(orig))
	SanitizeRequestBody(req)

	got, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, got)
	assert.Equal(t, int64(len(orig)), req.ContentLength) // should remain as original length
}

func TestValidationMiddleware_POST_SanitizesAndPassesToNext(t *testing.T) {
	payload := map[string]interface{}{
		"content":     "A\x00B",
		"path":        "P\x0bQ",
		"old_content": "O\x1fL",
		"new_content": "N\x7fW",
		"other":       "X\x00Y",
	}
	body, err := json.Marshal(payload)
	assert.NoError(t, err)

	var seenContentLength int64
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenContentLength = r.ContentLength
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)

		var got map[string]string
		err = json.Unmarshal(b, &got)
		assert.NoError(t, err)

		assert.Equal(t, "AB", got["content"])
		assert.Equal(t, "PQ", got["path"])
		assert.Equal(t, "OL", got["old_content"])
		assert.Equal(t, "NW", got["new_content"])
		// other should remain unsanitized
		assert.Equal(t, "X\x00Y", got["other"])

		w.WriteHeader(http.StatusOK)
	})

	mw := ValidationMiddleware(next)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewReader(body))
	mw.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)
	// ContentLength should match the length of the sanitized body passed to handler
	assert.Greater(t, seenContentLength, int64(0))
}

func TestValidationMiddleware_NonPOST_PassesUnchanged(t *testing.T) {
	payload := map[string]interface{}{
		"content": "A\x00B",
		"other":   "X\x00Y",
	}
	body, err := json.Marshal(payload)
	assert.NoError(t, err)

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		var got map[string]string
		err = json.Unmarshal(b, &got)
		assert.NoError(t, err)
		// Non-POST should not sanitize
		assert.Equal(t, "A\x00B", got["content"])
		assert.Equal(t, "X\x00Y", got["other"])
		w.WriteHeader(http.StatusOK)
	})

	mw := ValidationMiddleware(next)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/mw", bytes.NewReader(body))
	mw.ServeHTTP(rec, req)
	assert.Equal(t, http.StatusOK, rec.Code)
}

func TestGetValidationErrors_CopyIndependence(t *testing.T) {
	ClearValidationErrors()
	_ = ValidateParseRequest("", "")
	errs1 := GetValidationErrors()
	assert.Len(t, errs1, 1)
	// mutate returned slice
	errs1[0].Field = "modified"

	// fetch again; internal store should be unchanged
	errs2 := GetValidationErrors()
	assert.Equal(t, "content", errs2[0].Field)
	assert.Equal(t, "Content is required and cannot be empty", errs2[0].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}
