package middleware

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest_ContentEmpty(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("", "valid/path")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "required")
	assert.WithinDuration(t, time.Now(), errors[0].Time, time.Second)

	logged := GetValidationErrors()
	assert.Len(t, logged, 1)
	assert.Equal(t, "content", logged[0].Field)
	ClearValidationErrors()
}

func TestValidateParseRequest_ContentTooBig(t *testing.T) {
	ClearValidationErrors()
	tooBig := strings.Repeat("a", MaxContentSize+1)
	errors := ValidateParseRequest(tooBig, "valid/path")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "exceeds maximum size")
	ClearValidationErrors()
}

func TestValidateParseRequest_ContentNullBytes(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("hello\x00world", "valid/path")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "invalid null bytes")
	ClearValidationErrors()
}

func TestValidateParseRequest_PathTooLong(t *testing.T) {
	ClearValidationErrors()
	longPath := strings.Repeat("p", MaxPathLength+1)
	errors := ValidateParseRequest("ok", longPath)
	assert.Len(t, errors, 1)
	assert.Equal(t, "path", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "maximum length")
	ClearValidationErrors()
}

func TestValidateParseRequest_PathTraversal(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("ok", "../etc/passwd")
	assert.Len(t, errors, 1)
	assert.Equal(t, "path", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "directory traversal")

	errors2 := ValidateParseRequest("ok", "~/secrets")
	assert.Len(t, errors2, 1)
	assert.Equal(t, "path", errors2[0].Field)
	assert.Contains(t, errors2[0].Reason, "directory traversal")
	ClearValidationErrors()
}

func TestValidateParseRequest_NoErrors(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("some content", "safe/path")
	assert.Len(t, errors, 0)
	assert.Len(t, GetValidationErrors(), 0)
}

func TestValidateDiffRequest_Required(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateDiffRequest("", "")
	assert.Len(t, errors, 2)
	fields := []string{errors[0].Field, errors[1].Field}
	assert.Contains(t, fields, "old_content")
	assert.Contains(t, fields, "new_content")
	assert.True(t, strings.Contains(errors[0].Reason, "required") || strings.Contains(errors[1].Reason, "required"))
	ClearValidationErrors()
}

func TestValidateDiffRequest_SizeExceeded(t *testing.T) {
	ClearValidationErrors()
	s := strings.Repeat("a", MaxContentSize+1)
	errors := ValidateDiffRequest(s, s)
	assert.Len(t, errors, 2)
	for _, e := range errors {
		assert.True(t, e.Field == "old_content" || e.Field == "new_content")
		assert.Contains(t, e.Reason, "exceeds maximum size")
	}
	ClearValidationErrors()
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	input := "Hello\x00World\x1F!\n\t\r\x0B\x0C"
	out := SanitizeInput(input)
	assert.Equal(t, "HelloWorld!\n\t\r", out)

	// Ensure other normal characters are preserved
	input2 := "A\x01B\x02C D"
	out2 := SanitizeInput(input2)
	assert.Equal(t, "ABC D", out2)
}

func TestSanitizeRequestBody_JSONSanitization(t *testing.T) {
	body := `{
		"content": "val\x00id\n",
		"path": "p\x0Bq",
		"old_content": "old\x11",
		"new_content": "new\x7F"
	}`
	req := httptest.NewRequest(http.MethodPost, "/test", bytes.NewBufferString(body))
	SanitizeRequestBody(req)

	readBack, err := ioutilReadAllAndRestore(req)
	assert.NoError(t, err)

	var data map[string]string
	err = json.Unmarshal(readBack, &data)
	assert.NoError(t, err)

	assert.Equal(t, "valid\n", data["content"])
	assert.Equal(t, "pq", data["path"])
	assert.Equal(t, "old", data["old_content"])
	assert.Equal(t, "new", data["new_content"])
	assert.Equal(t, int64(len(readBack)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_RestoresBody(t *testing.T) {
	orig := "not json"
	req := httptest.NewRequest(http.MethodPost, "/test", bytes.NewBufferString(orig))
	SanitizeRequestBody(req)

	readBack, err := ioutilReadAllAndRestore(req)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(readBack))
}

func TestValidationMiddleware_NonPost_PassesThrough(t *testing.T) {
	orig := `{"content":"a\x00b"}`
	req := httptest.NewRequest(http.MethodGet, "/mw", bytes.NewBufferString(orig))
	rr := httptest.NewRecorder()

	var seen string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := ioutilReadAllAndRestore(r)
		seen = string(b)
		w.WriteHeader(http.StatusOK)
	})

	ValidationMiddleware(next).ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, orig, seen)
}

func TestValidationMiddleware_Post_SanitizesJSON(t *testing.T) {
	body := `{
		"content": "hi\x00",
		"path": "a\x0Bb",
		"old_content": "o\x11",
		"new_content": "n\x7F"
	}`
	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewBufferString(body))
	rr := httptest.NewRecorder()

	var sanitized map[string]string
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := ioutilReadAllAndRestore(r)
		_ = json.Unmarshal(b, &sanitized)
		w.WriteHeader(http.StatusNoContent)
	})

	ValidationMiddleware(next).ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNoContent, rr.Code)
	assert.Equal(t, "hi", sanitized["content"])
	assert.Equal(t, "ab", sanitized["path"])
	assert.Equal(t, "o", sanitized["old_content"])
	assert.Equal(t, "n", sanitized["new_content"])
}

func TestGetValidationErrors_ReturnsCopy(t *testing.T) {
	ClearValidationErrors()
	now := time.Now()
	orig := []ValidationError{{Field: "f", Reason: "r", Time: now}}
	logValidationErrors(orig)

	got := GetValidationErrors()
	assert.Len(t, got, 1)
	got[0].Reason = "modified"

	got2 := GetValidationErrors()
	assert.Equal(t, "r", got2[0].Reason)
	ClearValidationErrors()
}

func TestLogValidationErrors_CapAt100(t *testing.T) {
	ClearValidationErrors()
	for i := 0; i < 120; i++ {
		logValidationErrors([]ValidationError{
			{Field: fmt.Sprintf("f%d", i), Reason: fmt.Sprintf("r%d", i), Time: time.Now()},
		})
	}
	errs := GetValidationErrors()
	assert.Len(t, errs, 100)
	assert.Equal(t, "f20", errs[0].Field)
	assert.Equal(t, "r20", errs[0].Reason)
	assert.Equal(t, "f119", errs[99].Field)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("abc\x00def"))
	assert.False(t, containsNullBytes("abcdef"))
}

// helper to read all from req.Body and restore it
func ioutilReadAllAndRestore(r *http.Request) ([]byte, error) {
	b, err := ioReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	r.Body = ioNopCloser(bytes.NewBuffer(b))
	return b, nil
}

// local shims to avoid importing deprecated ioutil in older/newer Go versions
func ioReadAll(rc interface{ Read([]byte) (int, error) }) ([]byte, error) {
	var buf bytes.Buffer
	_, err := buf.ReadFrom(rc)
	return buf.Bytes(), err
}

type nopCloser struct {
	*bytes.Buffer
}

func (nopCloser) Close() error { return nil }

func ioNopCloser(b *bytes.Buffer) nopCloser {
	return nopCloser{b}
}
