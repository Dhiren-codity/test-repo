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

func TestValidateParseRequest_EmptyContent_LogsAndReturnsError(t *testing.T) {
	ClearValidationErrors()

	errors := ValidateParseRequest("", "safe/path")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Equal(t, "Content is required and cannot be empty", errors[0].Reason)
	assert.False(t, errors[0].Time.IsZero())

	logged := GetValidationErrors()
	assert.Len(t, logged, 1)
	assert.Equal(t, "content", logged[0].Field)
	assert.Equal(t, "Content is required and cannot be empty", logged[0].Reason)
	assert.False(t, logged[0].Time.IsZero())

	ClearValidationErrors()
}

func TestValidateParseRequest_ContentNullBytes(t *testing.T) {
	ClearValidationErrors()

	errors := ValidateParseRequest("abc\x00def", "")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Equal(t, "Content contains invalid null bytes", errors[0].Reason)

	logged := GetValidationErrors()
	assert.Len(t, logged, 1)
	assert.Equal(t, "content", logged[0].Field)
	assert.Equal(t, "Content contains invalid null bytes", logged[0].Reason)

	ClearValidationErrors()
}

func TestValidateParseRequest_PathTooLongAndTraversal(t *testing.T) {
	ClearValidationErrors()

	longPath := strings.Repeat("a", MaxPathLength+1) + "../unsafe"
	errors := ValidateParseRequest("ok", longPath)
	// Expect two errors: length and traversal
	assert.Len(t, errors, 2)

	fields := map[string]int{}
	reasons := map[string]bool{}
	for _, e := range errors {
		fields[e.Field]++
		reasons[e.Reason] = true
		assert.False(t, e.Time.IsZero())
	}
	assert.Equal(t, 2, fields["path"])
	assert.True(t, reasons["Path exceeds maximum length"])
	assert.True(t, reasons["Path contains potential directory traversal"])

	// Logged
	logged := GetValidationErrors()
	assert.Len(t, logged, 2)

	ClearValidationErrors()
}

func TestValidateParseRequest_ContentTooLarge(t *testing.T) {
	ClearValidationErrors()

	content := strings.Repeat("x", MaxContentSize+1)
	errors := ValidateParseRequest(content, "safe")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Equal(t, "Content exceeds maximum size of 1MB", errors[0].Reason)

	ClearValidationErrors()
}

func TestValidateDiffRequest_RequiredFields(t *testing.T) {
	ClearValidationErrors()

	errors := ValidateDiffRequest("", "")
	assert.Len(t, errors, 2)

	reasons := map[string]bool{}
	fields := map[string]int{}
	for _, e := range errors {
		reasons[e.Reason] = true
		fields[e.Field]++
		assert.False(t, e.Time.IsZero())
	}
	assert.True(t, reasons["Old content is required"])
	assert.True(t, reasons["New content is required"])
	assert.Equal(t, 1, fields["old_content"])
	assert.Equal(t, 1, fields["new_content"])

	// Logged contains both
	logged := GetValidationErrors()
	assert.Len(t, logged, 2)

	ClearValidationErrors()
}

func TestValidateDiffRequest_MaxSize(t *testing.T) {
	ClearValidationErrors()

	tooLong := strings.Repeat("y", MaxContentSize+1)
	errors := ValidateDiffRequest(tooLong, "ok")
	assert.Len(t, errors, 1)
	assert.Equal(t, "old_content", errors[0].Field)
	assert.Equal(t, "Old content exceeds maximum size", errors[0].Reason)

	errors = ValidateDiffRequest("ok", tooLong)
	assert.Len(t, errors, 1)
	assert.Equal(t, "new_content", errors[0].Field)
	assert.Equal(t, "New content exceeds maximum size", errors[0].Reason)

	ClearValidationErrors()
}

func TestValidationErrors_CappedAt100(t *testing.T) {
	ClearValidationErrors()

	for i := 0; i < 120; i++ {
		_ = ValidateDiffRequest("", "ok") // logs one error each call (old_content required)
	}
	logged := GetValidationErrors()
	assert.Len(t, logged, 100)
	for _, e := range logged {
		assert.Equal(t, "old_content", e.Field)
		assert.Equal(t, "Old content is required", e.Reason)
	}
	ClearValidationErrors()
}

func TestGetClearValidationErrors_CopyIsolation(t *testing.T) {
	ClearValidationErrors()

	_ = ValidateParseRequest("", "")
	orig := GetValidationErrors()
	assert.Len(t, orig, 1)
	assert.Equal(t, "content", orig[0].Field)

	// Mutate copy
	mut := GetValidationErrors()
	mut[0].Field = "tampered"

	// Original remains unchanged
	again := GetValidationErrors()
	assert.Equal(t, "content", again[0].Field)

	ClearValidationErrors()
}

func TestSanitizeInput_RemovesDisallowedControls(t *testing.T) {
	in := "A\x00B\x01C\x02D\x0bE\x0cF\x0eG\x1fH\x7fI\nJ\tK\rL"
	out := SanitizeInput(in)
	assert.Equal(t, "ABCDEFGHI\nJ\tK\rL", out)

	// Ensure non-control unicode preserved
	in2 := "Z😊\x00Y"
	out2 := SanitizeInput(in2)
	assert.Equal(t, "Z😊Y", out2)
}

func TestSanitizeRequestBody_SanitizesJSON(t *testing.T) {
	body := map[string]string{
		"content":     "Hello\x00World",
		"path":        "abc\x00def",
		"old_content": "o\x01ld",
		"new_content": "n\x02ew",
	}
	b, _ := json.Marshal(body)

	r := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewReader(b))
	SanitizeRequestBody(r)

	// Read back sanitized body
	var got map[string]string
	dec := json.NewDecoder(r.Body)
	err := dec.Decode(&got)
	assert.NoError(t, err)

	assert.Equal(t, SanitizeInput(body["content"]), got["content"])
	assert.Equal(t, SanitizeInput(body["path"]), got["path"])
	assert.Equal(t, SanitizeInput(body["old_content"]), got["old_content"])
	assert.Equal(t, SanitizeInput(body["new_content"]), got["new_content"])

	// ContentLength should be updated to sanitized body length
	sanitized, _ := json.Marshal(got)
	assert.Equal(t, int64(len(sanitized)), r.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_PreservesBody(t *testing.T) {
	orig := []byte("not-json")
	r := httptest.NewRequest(http.MethodPost, "/sanitize", bytes.NewReader(orig))

	SanitizeRequestBody(r)

	read, _ := io.ReadAll(r.Body)
	assert.Equal(t, string(orig), string(read))
}

func TestValidationMiddleware_POST_SanitizesAndSetsContentLength(t *testing.T) {
	// next handler echoes body and exposes ContentLength via header
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Len", func() string {
			return strconv64(r.ContentLength)
		}())
		body, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
	})

	handler := ValidationMiddleware(next)

	// Input with control chars
	body := map[string]string{
		"content":     "A\x00B",
		"path":        "P\x01Q",
		"old_content": "O\x02L",
		"new_content": "N\x03W",
	}
	raw, _ := json.Marshal(body)

	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewReader(raw))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()

	var got map[string]string
	_ = json.NewDecoder(resp.Body).Decode(&got)

	assert.Equal(t, SanitizeInput(body["content"]), got["content"])
	assert.Equal(t, SanitizeInput(body["path"]), got["path"])
	assert.Equal(t, SanitizeInput(body["old_content"]), got["old_content"])
	assert.Equal(t, SanitizeInput(body["new_content"]), got["new_content"])

	sanitized, _ := json.Marshal(got)
	assert.Equal(t, strconv64(int64(len(sanitized))), resp.Header.Get("X-Len"))
}

func TestValidationMiddleware_NonPOST_PassesThroughUnchanged(t *testing.T) {
	// next echoes body
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
	})

	handler := ValidationMiddleware(next)

	body := map[string]string{
		"content": "A\x00B",
	}
	raw, _ := json.Marshal(body)

	req := httptest.NewRequest(http.MethodGet, "/mw", bytes.NewReader(raw))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()

	var got map[string]string
	_ = json.NewDecoder(resp.Body).Decode(&got)
	// Should be unchanged
	assert.Equal(t, body["content"], got["content"])
}

func TestValidationMiddleware_POST_InvalidJSON_PassThroughUnchanged(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
	})
	handler := ValidationMiddleware(next)

	raw := []byte("not-json")
	req := httptest.NewRequest(http.MethodPost, "/mw", bytes.NewReader(raw))
	rec := httptest.NewRecorder()

	handler.ServeHTTP(rec, req)

	resp := rec.Result()
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	assert.Equal(t, "not-json", string(body))
}

// helper to convert int64 to string without importing strconv repeatedly
func strconv64(n int64) string {
	// simple decimal conversion
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
