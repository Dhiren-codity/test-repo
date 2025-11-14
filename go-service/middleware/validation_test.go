package middleware

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestValidateDiffRequest_Scenarios(t *testing.T) {
	ClearValidationErrors()

	// Both empty
	errs := ValidateDiffRequest("", "")
	assert.Equal(t, 2, len(errs))
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "required")
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Contains(t, errs[1].Reason, "required")

	// One empty, one valid
	errs = ValidateDiffRequest("old", "")
	assert.Equal(t, 1, len(errs))
	assert.Equal(t, "new_content", errs[0].Field)

	// Both too large
	large := strings.Repeat("x", MaxContentSize+1)
	errs = ValidateDiffRequest(large, large)
	assert.Equal(t, 2, len(errs))
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "exceeds maximum size")
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Contains(t, errs[1].Reason, "exceeds maximum size")

	// Valid
	errs = ValidateDiffRequest("hello", "world")
	assert.Equal(t, 0, len(errs))
}

func TestSanitizeInput_RemovesControlsKeepsWhitespace(t *testing.T) {
	// Includes: NUL, BEL, RS, DEL, and LRM (U+200E). Keeps \n, \r, \t
	in := "A\x00B\x07C\nD\rE\tF\x1EG\x7fH\u200EI"
	out := SanitizeInput(in)
	// LRM is preserved by current implementation
	assert.Equal(t, "ABC\nD\rE\tFGH\u200EI", out)
}

func TestSanitizeRequestBody_JSONAndNonJSON(t *testing.T) {
	{
		body := `{"content":"A\u0000B","path":"ok\u0007","old_content":"X\u200EY","new_content":"M\u001EN"}`
		r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")

		SanitizeRequestBody(r)

		defer r.Body.Close()
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Greater(t, r.ContentLength, int64(0))

		var m map[string]string
		err = json.Unmarshal(b, &m)
		assert.NoError(t, err)
		assert.Equal(t, "AB", m["content"])
		assert.Equal(t, "ok", m["path"])
		// LRM preserved
		assert.Equal(t, "X\u200EY", m["old_content"])
		assert.Equal(t, "MN", m["new_content"])
	}

	{
		// Non-JSON payload should be preserved as-is
		orig := "notjson\u0000with null and \u0007bell"
		r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(orig))
		SanitizeRequestBody(r)

		defer r.Body.Close()
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, orig, string(b))
	}
}

func TestValidationMiddleware_SanitizesPostJSON(t *testing.T) {
	body := `{"content":"A\u0000B","path":"../x\u0007","old_content":"X\u200EY","new_content":"M\u001EN"}`
	rec := httptest.NewRecorder()

	var seen map[string]string
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Greater(t, r.ContentLength, int64(0))
		err = json.Unmarshal(b, &seen)
		assert.NoError(t, err)
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, "AB", seen["content"])
	// path is sanitized only for control chars; traversal stays because it's not a control char
	assert.Equal(t, "../x", seen["path"])
	// LRM preserved
	assert.Equal(t, "X\u200EY", seen["old_content"])
	assert.Equal(t, "MN", seen["new_content"])
}

func TestValidationMiddleware_PostInvalidJSONPassesThrough(t *testing.T) {
	orig := `{"content":"A` // invalid JSON
	rec := httptest.NewRecorder()

	var seen string
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		seen = string(b)
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(orig))
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, orig, seen)
}

func TestValidationMiddleware_NonPostNoChange(t *testing.T) {
	orig := "GET body \u0000 with control"
	rec := httptest.NewRecorder()

	var seen string
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer r.Body.Close()
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		seen = string(b)
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/", strings.NewReader(orig))
	handler.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	assert.Equal(t, orig, seen)
}

func TestGetAndClearValidationErrors_CopyIsolationAndRetention(t *testing.T) {
	// Start clean
	ClearValidationErrors()

	// Initially empty
	errs := GetValidationErrors()
	assert.Equal(t, 0, len(errs))

	// Log some errors
	logValidationErrors([]ValidationError{
		{Field: "f1", Reason: "r1", Time: errsTimeNow()},
	})
	logValidationErrors([]ValidationError{
		{Field: "f2", Reason: "r2", Time: errsTimeNow()},
	})

	// Should have 2
	errs = GetValidationErrors()
	assert.Equal(t, 2, len(errs))
	assert.Equal(t, "f1", errs[0].Field)
	assert.Equal(t, "f2", errs[1].Field)

	// Mutate returned slice and ensure internal state not affected
	errs[0].Field = "mutated"
	errs2 := GetValidationErrors()
	assert.Equal(t, "f1", errs2[0].Field)

	// Test retention to last 100
	ClearValidationErrors()
	for i := 0; i < 110; i++ {
		ev := ValidationError{
			Field:  "f" + strconv.Itoa(i),
			Reason: "r-" + strconv.Itoa(i),
			Time:   errsTimeNow(),
		}
		logValidationErrors([]ValidationError{ev})
	}
	errs = GetValidationErrors()
	assert.Equal(t, 100, len(errs))
	// Should retain last 100 from 10..109
	assert.Equal(t, "r-10", errs[0].Reason, "first retained should be index 10")
	assert.Equal(t, "r-109", errs[len(errs)-1].Reason, "last retained should be index 109")

	// Clear works
	ClearValidationErrors()
	assert.Equal(t, 0, len(GetValidationErrors()))
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}

// errsTimeNow exists so tests can compile-time set a time without relying on time.Now() directly.
func errsTimeNow() time.Time {
	return time.Now()
}

func TestValidateParseRequest_LogsErrors(t *testing.T) {
	ClearValidationErrors()

	// Trigger a validation error to be logged
	_ = ValidateParseRequest("", "safe")
	errs := GetValidationErrors()
	assert.Equal(t, 1, len(errs))
	assert.Equal(t, "content", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "required")
}

func TestSanitizeRequestBody_ContentLengthUpdated(t *testing.T) {
	body := `{"content":"A\u0000\u0000\u0000B"}`
	r := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	SanitizeRequestBody(r)

	b, err := io.ReadAll(r.Body)
	assert.NoError(t, err)
	assert.Equal(t, int64(len(b)), r.ContentLength)

	var m map[string]string
	err = json.Unmarshal(b, &m)
	assert.NoError(t, err)
	assert.Equal(t, "AB", m["content"])
}

func TestValidateDiffRequest_EdgeCases(t *testing.T) {
	// Large old, empty new -> two errors (one for each condition)
	large := strings.Repeat("Z", MaxContentSize+1)
	errs := ValidateDiffRequest(large, "")
	assert.Equal(t, 2, len(errs))
	fields := []string{errs[0].Field, errs[1].Field}
	assert.Contains(t, fields, "old_content")
	assert.Contains(t, fields, "new_content")
}

func TestValidateParseRequest_PathTraversalVariants(t *testing.T) {
	// "~/" pattern
	errs := ValidateParseRequest("ok", "~/foo/bar")
	assert.Equal(t, 1, len(errs))
	assert.Equal(t, "path", errs[0].Field)
	assert.Contains(t, errs[0].Reason, "directory traversal")

	// Both patterns and over length
	path := strings.Repeat("../", (MaxPathLength/3)+1)
	errs = ValidateParseRequest("ok", path)
	assert.Equal(t, 2, len(errs))
	reasons := []string{errs[0].Reason, errs[1].Reason}
	joined := strings.Join(reasons, " | ")
	assert.Contains(t, joined, "maximum length")
	assert.Contains(t, joined, "directory traversal")
}

func TestSanitizeInput_LeavesPrintableRunes(t *testing.T) {
	in := "Hello, 世界!\nNew\tLine\rCarriage"
	out := SanitizeInput(in)
	assert.Equal(t, in, out, fmt.Sprintf("expected printable runes to remain unchanged"))
}
