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

func TestValidateParseRequest_NoErrors(t *testing.T) {
	ClearValidationErrors()
	content := "valid content"
	path := "dir/subdir/file.txt"
	errs := ValidateParseRequest(content, path)
	assert.Empty(t, errs)

	stored := GetValidationErrors()
	assert.Empty(t, stored)
}

func TestValidateParseRequest_Errors(t *testing.T) {
	ClearValidationErrors()
	tooLarge := strings.Repeat("a", int(MaxContentSize)+1)
	tooLongPath := strings.Repeat("p", MaxPathLength+1)

	tests := []struct {
		name    string
		content string
		path    string
		wantErr ValidationError
	}{
		{
			name:    "empty content",
			content: "",
			path:    "",
			wantErr: ValidationError{
				Field:  "content",
				Reason: "Content is required and cannot be empty",
			},
		},
		{
			name:    "content exceeds size",
			content: tooLarge,
			path:    "ok",
			wantErr: ValidationError{
				Field:  "content",
				Reason: "Content exceeds maximum size of 1MB",
			},
		},
		{
			name:    "content has null bytes",
			content: "abc\x00def",
			path:    "ok",
			wantErr: ValidationError{
				Field:  "content",
				Reason: "Content contains invalid null bytes",
			},
		},
		{
			name:    "path too long",
			content: "ok",
			path:    tooLongPath,
			wantErr: ValidationError{
				Field:  "path",
				Reason: "Path exceeds maximum length",
			},
		},
		{
			name:    "path traversal dotdot",
			content: "ok",
			path:    "../etc/passwd",
			wantErr: ValidationError{
				Field:  "path",
				Reason: "Path contains potential directory traversal",
			},
		},
		{
			name:    "path traversal tilde",
			content: "ok",
			path:    "~/secrets",
			wantErr: ValidationError{
				Field:  "path",
				Reason: "Path contains potential directory traversal",
			},
		},
	}

	for _, tt := range tests {
		errs := ValidateParseRequest(tt.content, tt.path)
		assert.NotEmpty(t, errs, tt.name)
		var found bool
		for _, e := range errs {
			if e.Field == tt.wantErr.Field && e.Reason == tt.wantErr.Reason {
				found = true
			}
		}
		assert.True(t, found, tt.name)
	}

	// Ensure errors were logged
	stored := GetValidationErrors()
	assert.GreaterOrEqual(t, len(stored), len(tests))
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestValidateDiffRequest(t *testing.T) {
	ClearValidationErrors()

	tooLarge := strings.Repeat("b", int(MaxContentSize)+1)

	// Both empty
	errs := ValidateDiffRequest("", "")
	assert.Len(t, errs, 2)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Equal(t, "Old content is required", errs[0].Reason)
	assert.Equal(t, "new_content", errs[1].Field)
	assert.Equal(t, "New content is required", errs[1].Reason)

	// Old too large
	errs = ValidateDiffRequest(tooLarge, "ok")
	assert.Len(t, errs, 1)
	assert.Equal(t, "old_content", errs[0].Field)
	assert.Equal(t, "Old content exceeds maximum size", errs[0].Reason)

	// New too large
	errs = ValidateDiffRequest("ok", tooLarge)
	assert.Len(t, errs, 1)
	assert.Equal(t, "new_content", errs[0].Field)
	assert.Equal(t, "New content exceeds maximum size", errs[0].Reason)

	// Both ok
	errs = ValidateDiffRequest("old", "new")
	assert.Empty(t, errs)
}

func TestSanitizeInput(t *testing.T) {
	// Remove null, bell, escape, DEL but keep \n, \r, \t
	in := " A\x00B\x07C\nD\tE\rF\x1BG\x7fH "
	out := SanitizeInput(in)
	// Spaces should be preserved; only control chars (except \n,\r,\t) removed
	assert.Equal(t, " AB C\nD\tE\rFGH ", out)

	// No changes to normal text
	assert.Equal(t, "hello world", SanitizeInput("hello world"))
}

func TestSanitizeRequestBody_JSON(t *testing.T) {
	body := `{
		"content": "A\u0000B\n",
		"path": "../\u001Bfile",
		"old_content": "",
		"new_content": "\u007Fz",
		"other": "\u0007keep"
	}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))
	SanitizeRequestBody(req)

	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	var data map[string]interface{}
	assert.NoError(t, json.Unmarshal(b, &data))

	assert.Equal(t, "AB\n", data["content"])
	assert.Equal(t, "../file", data["path"])
	assert.Equal(t, "", data["old_content"])
	assert.Equal(t, "z", data["new_content"])
	// "other" should remain unsanitized since it's not one of the handled keys
	assert.Equal(t, "\u0007keep", data["other"])

	assert.Equal(t, int64(len(b)), req.ContentLength)
}

func TestSanitizeRequestBody_InvalidJSON(t *testing.T) {
	orig := "not a json payload \x00 keep as is"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))
	SanitizeRequestBody(req)
	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(b))
}

func TestValidationMiddleware_POST_Sanitizes(t *testing.T) {
	body := `{"content":"A\u0000B","path":"x\u001By","old_content":"ok","new_content":"\u007Fz"}`
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(body))

	var seen []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen = b
		w.WriteHeader(http.StatusNoContent)
	})

	rr := httptest.NewRecorder()
	ValidationMiddleware(next).ServeHTTP(rr, req)
	assert.Equal(t, http.StatusNoContent, rr.Code)

	var got map[string]string
	assert.NoError(t, json.Unmarshal(seen, &got))
	assert.Equal(t, "AB", got["content"])
	assert.Equal(t, "xy", got["path"])
	assert.Equal(t, "ok", got["old_content"])
	assert.Equal(t, "z", got["new_content"])
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	orig := `{"content":"A\u0000B"}`
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(orig))

	var seen []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen = b
		w.WriteHeader(http.StatusOK)
	})
	rr := httptest.NewRecorder()
	ValidationMiddleware(next).ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, orig, string(seen))
}

func TestValidationMiddleware_POST_InvalidJSON_PassThrough(t *testing.T) {
	orig := "this is not json \x00 raw"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	var seen []byte
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		seen = b
		w.WriteHeader(http.StatusOK)
	})
	rr := httptest.NewRecorder()
	ValidationMiddleware(next).ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	assert.Equal(t, orig, string(seen))
}

func TestValidationErrors_StoreAndClear(t *testing.T) {
	ClearValidationErrors()

	// No errors logged when validation passes
	_ = ValidateParseRequest("ok", "file")
	assert.Empty(t, GetValidationErrors())

	// Generate many errors to test capping at 100
	for i := 0; i < 120; i++ {
		_ = ValidateParseRequest("", "")
	}
	errs := GetValidationErrors()
	assert.Len(t, errs, 100)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}
