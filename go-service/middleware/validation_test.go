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

func resetValidation() {
	ClearValidationErrors()
}

func TestValidateParseRequest_EmptyContent(t *testing.T) {
	resetValidation()
	errors := ValidateParseRequest("", "valid/path.txt")
	if assert.Len(t, errors, 1) {
		assert.Equal(t, "content", errors[0].Field)
		assert.Equal(t, "Content is required and cannot be empty", errors[0].Reason)
	}
	logged := GetValidationErrors()
	assert.Len(t, logged, 1)
	resetValidation()
}

func TestValidateParseRequest_ContentTooLarge(t *testing.T) {
	resetValidation()
	large := strings.Repeat("a", MaxContentSize+1)
	errors := ValidateParseRequest(large, "path")
	if assert.Len(t, errors, 1) {
		assert.Equal(t, "content", errors[0].Field)
		assert.Equal(t, "Content exceeds maximum size of 1MB", errors[0].Reason)
	}
	resetValidation()
}

func TestValidateParseRequest_NullBytesInContent(t *testing.T) {
	resetValidation()
	errors := ValidateParseRequest("abc\x00def", "path")
	if assert.Len(t, errors, 1) {
		assert.Equal(t, "content", errors[0].Field)
		assert.Equal(t, "Content contains invalid null bytes", errors[0].Reason)
	}
	resetValidation()
}

func TestValidateParseRequest_PathTooLong(t *testing.T) {
	resetValidation()
	longPath := strings.Repeat("p", MaxPathLength+1)
	errors := ValidateParseRequest("content", longPath)
	if assert.Len(t, errors, 1) {
		assert.Equal(t, "path", errors[0].Field)
		assert.Equal(t, "Path exceeds maximum length", errors[0].Reason)
	}
	resetValidation()
}

func TestValidateParseRequest_PathTraversal(t *testing.T) {
	resetValidation()
	errors := ValidateParseRequest("content", "/tmp/../../etc/passwd")
	if assert.Len(t, errors, 1) {
		assert.Equal(t, "path", errors[0].Field)
		assert.Equal(t, "Path contains potential directory traversal", errors[0].Reason)
	}
	resetValidation()
}

func TestValidateParseRequest_ValidInput_NoErrors(t *testing.T) {
	resetValidation()
	errors := ValidateParseRequest("hello world", "folder/file.txt")
	assert.Empty(t, errors)
	resetValidation()
}

func TestValidateDiffRequest_EmptyBoth(t *testing.T) {
	resetValidation()
	errors := ValidateDiffRequest("", "")
	if assert.Len(t, errors, 2) {
		assert.Equal(t, "old_content", errors[0].Field)
		assert.Equal(t, "Old content is required", errors[0].Reason)
		assert.Equal(t, "new_content", errors[1].Field)
		assert.Equal(t, "New content is required", errors[1].Reason)
	}
	resetValidation()
}

func TestValidateDiffRequest_OversizeBoth(t *testing.T) {
	resetValidation()
	large := strings.Repeat("x", MaxContentSize+1)
	errors := ValidateDiffRequest(large, large)
	if assert.Len(t, errors, 2) {
		assert.Equal(t, "old_content", errors[0].Field)
		assert.Equal(t, "Old content exceeds maximum size", errors[0].Reason)
		assert.Equal(t, "new_content", errors[1].Field)
		assert.Equal(t, "New content exceeds maximum size", errors[1].Reason)
	}
	resetValidation()
}

func TestValidateDiffRequest_Valid_NoErrors(t *testing.T) {
	resetValidation()
	errors := ValidateDiffRequest("old", "new")
	assert.Empty(t, errors)
	resetValidation()
}

func TestSanitizeInput_RemovesInvalidControlsAndKeepsAllowed(t *testing.T) {
	in := "hello\x00world\tline\ncarriage\rreturn\x01\x02"
	out := SanitizeInput(in)
	assert.Equal(t, "helloworld\tline\ncarriage\rreturn", out)
}

func TestSanitizeRequestBody_SanitizesJSONFields(t *testing.T) {
	body := map[string]string{
		"content":     "a\x00b\x01c",
		"path":        "../p\x7Fath",
		"old_content": "old\x00",
		"new_content": "new\x0E",
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(raw))

	SanitizeRequestBody(req)

	gotBytes, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	var got map[string]string
	err = json.Unmarshal(gotBytes, &got)
	assert.NoError(t, err)

	assert.Equal(t, "abc", got["content"])
	assert.Equal(t, "../path", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])
	assert.Equal(t, int64(len(gotBytes)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON_PreservesBody(t *testing.T) {
	orig := "not a json"
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(orig))

	SanitizeRequestBody(req)

	got, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(got))
}

func TestValidationMiddleware_SanitizesPostBody(t *testing.T) {
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		var data map[string]string
		err = json.Unmarshal(b, &data)
		assert.NoError(t, err)
		assert.Equal(t, "abc", data["content"])
		w.WriteHeader(http.StatusOK)
	}))

	reqBody := `{"content":"a\x00b\x01c"}`
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(reqBody))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Result().StatusCode)
}

func TestValidationMiddleware_PassthroughGet(t *testing.T) {
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, `{"content":"a`+"\x00"+`b"}`, string(b))
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/", strings.NewReader(`{"content":"a`+"\x00"+`b"}`))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Result().StatusCode)
}

func TestValidationMiddleware_InvalidJSON_PreservesPostBody(t *testing.T) {
	handler := ValidationMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		assert.Equal(t, "not json", string(b))
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodPost, "/", strings.NewReader("not json"))
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	assert.Equal(t, http.StatusOK, rr.Result().StatusCode)
}

func TestGetAndClearValidationErrors(t *testing.T) {
	resetValidation()
	errs := []ValidationError{
		{Field: "f1", Reason: "r1"},
		{Field: "f2", Reason: "r2"},
	}
	logValidationErrors(errs)
	got := GetValidationErrors()
	assert.Len(t, got, 2)
	ClearValidationErrors()
	got = GetValidationErrors()
	assert.Empty(t, got)
}

func TestLogValidationErrors_CappedAt100(t *testing.T) {
	resetValidation()
	for i := 0; i < 105; i++ {
		logValidationErrors([]ValidationError{{Field: "field" + strconvIt(i), Reason: "reason"}})
	}
	got := GetValidationErrors()
	if assert.Len(t, got, 100) {
		assert.Equal(t, "field5", got[0].Field)
		assert.Equal(t, "field104", got[99].Field)
	}
	resetValidation()
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func strconvIt(i int) string {
	// Lightweight int to string to avoid extra import
	return string(intToBytes(i))
}

func intToBytes(i int) []byte {
	// Convert int to decimal string bytes
	if i == 0 {
		return []byte{'0'}
	}
	var buf [20]byte
	pos := len(buf)
	n := i
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	return buf[pos:]
}
