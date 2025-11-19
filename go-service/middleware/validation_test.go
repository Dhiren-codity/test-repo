package middleware

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestValidateParseRequest_Table(t *testing.T) {
	tests := []struct {
		name      string
		content   string
		path      string
		wantCount int
		assertFns []func(t *testing.T, errs []ValidationError)
	}{
		{
			name:      "empty content",
			content:   "",
			path:      "file.txt",
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "content", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "Content is required")
				},
			},
		},
		{
			name:      "oversize content",
			content:   strings.Repeat("a", MaxContentSize+1),
			path:      "",
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "content", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "exceeds maximum size")
				},
			},
		},
		{
			name:      "content contains null byte",
			content:   "abc\x00def",
			path:      "",
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "content", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "null bytes")
				},
			},
		},
		{
			name:      "path too long",
			content:   "ok",
			path:      strings.Repeat("p", MaxPathLength+1),
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "path", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "maximum length")
				},
			},
		},
		{
			name:      "path traversal with ..",
			content:   "ok",
			path:      "../etc/passwd",
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "path", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "directory traversal")
				},
			},
		},
		{
			name:      "path traversal with ~/",
			content:   "ok",
			path:      "home/~/user",
			wantCount: 1,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					assert.Equal(t, "path", errs[0].Field)
					assert.Contains(t, errs[0].Reason, "directory traversal")
				},
			},
		},
		{
			name:      "both path errors",
			content:   "ok",
			path:      strings.Repeat("x", MaxPathLength+2) + "/~/bad",
			wantCount: 2,
			assertFns: []func(t *testing.T, errs []ValidationError){
				func(t *testing.T, errs []ValidationError) {
					fields := []string{errs[0].Field, errs[1].Field}
					assert.Contains(t, fields, "path")
					assert.Equal(t, 2, countField(errs, "path"))
				},
			},
		},
		{
			name:      "valid content and path",
			content:   "ok",
			path:      "valid/path",
			wantCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Len(t, errs, tt.wantCount)
			for _, fn := range tt.assertFns {
				fn(t, errs)
			}
		})
	}
}

func TestValidateParseRequest_LogsAndTruncates(t *testing.T) {
	// Ensure clean slate
	ClearValidationErrors()

	// First, a call that produces three errors (content empty + two path errors)
	longBadPath := strings.Repeat("a", MaxPathLength+1) + "/../"
	errs := ValidateParseRequest("", longBadPath)
	assert.Len(t, errs, 3)

	logged := GetValidationErrors()
	assert.Len(t, logged, 3)
	// Ensure fields present
	assert.Equal(t, "content", logged[0].Field)
	assert.Equal(t, "path", logged[1].Field)
	assert.Equal(t, "path", logged[2].Field)

	// Now overflow: add 150 more single-error validations
	for i := 0; i < 150; i++ {
		ValidateParseRequest("", "ok")
	}
	logged = GetValidationErrors()
	assert.Len(t, logged, 100) // truncated to last 100
}

func TestValidateDiffRequest_Table(t *testing.T) {
	tests := []struct {
		name      string
		oldC      string
		newC      string
		wantCount int
		wantHas   []string
	}{
		{
			name:      "both empty",
			oldC:      "",
			newC:      "",
			wantCount: 2,
			wantHas:   []string{"old_content", "new_content"},
		},
		{
			name:      "old oversize",
			oldC:      strings.Repeat("x", MaxContentSize+1),
			newC:      "ok",
			wantCount: 1,
			wantHas:   []string{"old_content"},
		},
		{
			name:      "new oversize",
			oldC:      "ok",
			newC:      strings.Repeat("y", MaxContentSize+1),
			wantCount: 1,
			wantHas:   []string{"new_content"},
		},
		{
			name:      "valid",
			oldC:      "old",
			newC:      "new",
			wantCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			errs := ValidateDiffRequest(tt.oldC, tt.newC)
			assert.Len(t, errs, tt.wantCount)
			for _, f := range tt.wantHas {
				assert.True(t, hasField(errs, f))
			}
		})
	}
}

func TestSanitizeInput(t *testing.T) {
	// Contains: null, SOH, BEL, LF, CR, TAB, US, DEL
	input := "Hello\x00World\x01!\nCarriage\rTab\tCtrl\x1FDel\x7FEnd"
	expected := "HelloWorld!\nCarriage\rTab\tCtrlDelEnd"
	out := SanitizeInput(input)
	assert.Equal(t, expected, out)
}

func TestSanitizeRequestBody_InvalidJSON_PreservesBody(t *testing.T) {
	orig := "not a json"
	req := httptest.NewRequest(http.MethodPost, "/", bytes.NewBufferString(orig))

	SanitizeRequestBody(req)

	b, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, string(b))
}

func TestValidationMiddleware_NonPOST_PassThrough(t *testing.T) {
	in := `{"content":"A\\u0000B"}`
	req := httptest.NewRequest(http.MethodGet, "/", bytes.NewBufferString(in))

	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(b)
	})

	rr := httptest.NewRecorder()
	ValidationMiddleware(next).ServeHTTP(rr, req)

	assert.Equal(t, http.StatusOK, rr.Code)
	// For non-POST, middleware should pass through unchanged
	assert.Equal(t, in, rr.Body.String())
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("a\x00b"))
	assert.False(t, containsNullBytes("abc"))
}

func TestGetAndClearValidationErrors(t *testing.T) {
	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())

	_ = ValidateParseRequest("", "ok") // logs one error
	errs := GetValidationErrors()
	assert.Len(t, errs, 1)
	assert.Equal(t, "content", errs[0].Field)

	ClearValidationErrors()
	assert.Empty(t, GetValidationErrors())
}

func hasField(errs []ValidationError, field string) bool {
	for _, e := range errs {
		if e.Field == field {
			return true
		}
	}
	return false
}

func countField(errs []ValidationError, field string) int {
	c := 0
	for _, e := range errs {
		if e.Field == field {
			c++
		}
	}
	return c
}
