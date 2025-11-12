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

func TestValidateParseRequest_EmptyContent(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("", "/valid/path.txt")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "required")

	logged := GetValidationErrors()
	assert.GreaterOrEqual(t, len(logged), 1)
}

func TestValidateParseRequest_ContentTooLarge(t *testing.T) {
	ClearValidationErrors()
	tooLarge := strings.Repeat("a", MaxContentSize+1)
	errors := ValidateParseRequest(tooLarge, "/file.txt")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "exceeds")

	logged := GetValidationErrors()
	assert.GreaterOrEqual(t, len(logged), 1)
}

func TestValidateParseRequest_ContentContainsNullByte(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("abc\x00def", "/file.txt")
	assert.Len(t, errors, 1)
	assert.Equal(t, "content", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "null")
}

func TestValidateParseRequest_PathTooLong(t *testing.T) {
	ClearValidationErrors()
	path := strings.Repeat("a", MaxPathLength+1)
	errors := ValidateParseRequest("content", path)
	assert.Len(t, errors, 1)
	assert.Equal(t, "path", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "maximum length")
}

func TestValidateParseRequest_PathTraversal(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("content", "../etc/passwd")
	assert.Len(t, errors, 1)
	assert.Equal(t, "path", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "directory traversal")

	ClearValidationErrors()
	errors = ValidateParseRequest("content", "~/secret")
	assert.Len(t, errors, 1)
	assert.Equal(t, "path", errors[0].Field)
	assert.Contains(t, errors[0].Reason, "directory traversal")
}

func TestValidateParseRequest_Valid(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateParseRequest("hello", "folder/file.txt")
	assert.Len(t, errors, 0)

	logged := GetValidationErrors()
	assert.Len(t, logged, 0)
}

func TestValidateDiffRequest_EmptyOldAndNew(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateDiffRequest("", "")
	assert.Len(t, errors, 2)
	fields := []string{errors[0].Field, errors[1].Field}
	assert.Contains(t, fields, "old_content")
	assert.Contains(t, fields, "new_content")

	logged := GetValidationErrors()
	assert.GreaterOrEqual(t, len(logged), 2)
}

func TestValidateDiffRequest_SizeExceeded(t *testing.T) {
	ClearValidationErrors()
	tooLarge := strings.Repeat("x", MaxContentSize+1)
	errors := ValidateDiffRequest(tooLarge, tooLarge)
	assert.Len(t, errors, 2)
	assert.Equal(t, "old_content", errors[0].Field)
	assert.Equal(t, "new_content", errors[1].Field)
	assert.Contains(t, errors[0].Reason, "exceeds")
	assert.Contains(t, errors[1].Reason, "exceeds")
}

func TestValidateDiffRequest_Valid(t *testing.T) {
	ClearValidationErrors()
	errors := ValidateDiffRequest("old", "new")
	assert.Len(t, errors, 0)

	logged := GetValidationErrors()
	assert.Len(t, logged, 0)
}

func TestSanitizeInput_RemovesDisallowedControls(t *testing.T) {
	input := "A\tB\nC\rD\x00E\x01F\x0bG\x0cH\x1FI\x7fJ"
	got := SanitizeInput(input)
	assert.Equal(t, "A\tB\nC\rDEFGHIJ", got)
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	bodyMap := map[string]string{
		"content":     "A\x00B",
		"path":        "x\x0b/y",
		"old_content": "old\x01",
		"new_content": "new\x7f",
	}
	bodyBytes, _ := json.Marshal(bodyMap)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(bodyBytes))

	SanitizeRequestBody(req)

	// Read back
	gotBody, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	var got map[string]string
	err = json.Unmarshal(gotBody, &got)
	assert.NoError(t, err)

	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "xy", got["path"])
	assert.Equal(t, "old", got["old_content"])
	assert.Equal(t, "new", got["new_content"])
	assert.Equal(t, int64(len(gotBody)), req.ContentLength)
}

func TestSanitizeRequestBody_NonJSON_PreservesBody(t *testing.T) {
	orig := []byte("not-json-\x00-here")
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(orig))
	SanitizeRequestBody(req)

	got, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, got)
}

func TestValidationMiddleware_SanitizesPOSTBody(t *testing.T) {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var data map[string]string
		_ = json.NewDecoder(r.Body).Decode(&data)
		_ = json.NewEncoder(w).Encode(data)
	})

	mw := ValidationMiddleware(h)

	bodyMap := map[string]string{
		"content":     "a\x00b",
		"path":        "p\x0bath",
		"old_content": "o\x01ld",
		"new_content": "n\x7few",
	}
	bodyBytes, _ := json.Marshal(bodyMap)
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewReader(bodyBytes))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	var out map[string]string
	assert.NoError(t, json.Unmarshal(rec.Body.Bytes(), &out))
	assert.Equal(t, "ab", out["content"])
	assert.Equal(t, "path", out["path"])
	assert.Equal(t, "old", out["old_content"])
	assert.Equal(t, "new", out["new_content"])
}

func TestValidationMiddleware_SkipForGET_NoSanitize(t *testing.T) {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var data map[string]string
		_ = json.NewDecoder(r.Body).Decode(&data)
		_ = json.NewEncoder(w).Encode(data)
	})

	mw := ValidationMiddleware(h)

	// Create GET request with body containing a null byte
	bodyMap := map[string]string{"content": "a\x00b"}
	bodyBytes, _ := json.Marshal(bodyMap)
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewReader(bodyBytes))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	// Expect the response to still contain null (escaped in JSON as \u0000)
	assert.Contains(t, rec.Body.String(), `a\u0000b`)
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	now := time.Now()
	logValidationErrors([]ValidationError{
		{Field: "f1", Reason: "r1", Time: now},
	})
	got := GetValidationErrors()
	assert.Len(t, got, 1)
	assert.Equal(t, "f1", got[0].Field)
	assert.Equal(t, "r1", got[0].Reason)

	// Modify returned slice and ensure internal state is unchanged
	got[0].Reason = "changed"
	got2 := GetValidationErrors()
	assert.Equal(t, "r1", got2[0].Reason)

	ClearValidationErrors()
	got3 := GetValidationErrors()
	assert.Len(t, got3, 0)
}

func TestLogValidationErrors_CapAt100(t *testing.T) {
	ClearValidationErrors()
	for i := 1; i <= 120; i++ {
		logValidationErrors([]ValidationError{
			{Field: "f", Reason: fmt.Sprintf("r%d", i), Time: time.Now()},
		})
	}
	got := GetValidationErrors()
	assert.Len(t, got, 100)
	assert.Equal(t, "r21", got[0].Reason)
	assert.Equal(t, "r120", got[len(got)-1].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}
