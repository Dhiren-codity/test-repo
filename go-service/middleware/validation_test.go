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

func TestValidateParseRequest(t *testing.T) {
	defer ClearValidationErrors()

	tests := []struct {
		name        string
		content     string
		path        string
		expectErrs  int
		expectField string
		expectInMsg string
	}{
		{
			name:        "empty content",
			content:     "",
			path:        "",
			expectErrs:  1,
			expectField: "content",
			expectInMsg: "Content is required",
		},
		{
			name:        "too large content",
			content:     strings.Repeat("a", MaxContentSize+1),
			path:        "",
			expectErrs:  1,
			expectField: "content",
			expectInMsg: "exceeds maximum size",
		},
		{
			name:        "content with null bytes",
			content:     "abc\x00def",
			path:        "",
			expectErrs:  1,
			expectField: "content",
			expectInMsg: "invalid null bytes",
		},
		{
			name:        "path too long",
			content:     "ok",
			path:        strings.Repeat("p", MaxPathLength+1),
			expectErrs:  1,
			expectField: "path",
			expectInMsg: "Path exceeds maximum length",
		},
		{
			name:        "path traversal dotdot",
			content:     "ok",
			path:        "foo/../bar",
			expectErrs:  1,
			expectField: "path",
			expectInMsg: "directory traversal",
		},
		{
			name:        "path traversal tilde",
			content:     "ok",
			path:        "~/bar",
			expectErrs:  1,
			expectField: "path",
			expectInMsg: "directory traversal",
		},
		{
			name:        "valid content and path",
			content:     "hello",
			path:        "safe/path",
			expectErrs:  0,
			expectField: "",
			expectInMsg: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateParseRequest(tt.content, tt.path)
			assert.Equal(t, tt.expectErrs, len(errs))
			if tt.expectErrs > 0 {
				found := false
				for _, e := range errs {
					if e.Field == tt.expectField && strings.Contains(e.Reason, tt.expectInMsg) {
						found = true
						break
					}
				}
				if !found {
					t.Fatalf("expected error with field=%q and reason containing %q, got: %#v", tt.expectField, tt.expectInMsg, errs)
				}
			}
		})
	}
}

func TestValidateDiffRequest(t *testing.T) {
	defer ClearValidationErrors()

	tests := []struct {
		name        string
		oldContent  string
		newContent  string
		expectErrs  int
		expectField string
		expectInMsg string
	}{
		{
			name:        "both empty",
			oldContent:  "",
			newContent:  "",
			expectErrs:  2,
			expectField: "old_content",
			expectInMsg: "required",
		},
		{
			name:        "old too large",
			oldContent:  strings.Repeat("a", MaxContentSize+1),
			newContent:  "ok",
			expectErrs:  1,
			expectField: "old_content",
			expectInMsg: "exceeds maximum size",
		},
		{
			name:        "new too large",
			oldContent:  "ok",
			newContent:  strings.Repeat("b", MaxContentSize+1),
			expectErrs:  1,
			expectField: "new_content",
			expectInMsg: "exceeds maximum size",
		},
		{
			name:        "valid",
			oldContent:  "old",
			newContent:  "new",
			expectErrs:  0,
			expectField: "",
			expectInMsg: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ClearValidationErrors()
			errs := ValidateDiffRequest(tt.oldContent, tt.newContent)
			assert.Equal(t, tt.expectErrs, len(errs))
			if tt.expectErrs > 0 {
				found := false
				for _, e := range errs {
					if e.Field == tt.expectField && strings.Contains(e.Reason, tt.expectInMsg) {
						found = true
						break
					}
				}
				if !found {
					t.Fatalf("expected error with field=%q and reason containing %q, got: %#v", tt.expectField, tt.expectInMsg, errs)
				}
			}
		})
	}
}

func TestSanitizeInput_RemovesControlCharacters(t *testing.T) {
	input := "Hello\x00World\x01!\nTab\tCR\rOk\u007fEnd"
	expected := "HelloWorld!\nTab\tCR\rOkEnd"
	out := SanitizeInput(input)
	assert.Equal(t, expected, out)
}

func TestSanitizeRequestBody_SanitizesKnownFields(t *testing.T) {
	body := map[string]any{
		"content":     "A\x00B\nC",
		"path":        "X\x01Y",
		"old_content": "E\u007fF",
		"new_content": "G\x08H\t",
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewReader(raw))

	SanitizeRequestBody(req)

	// Read back the body
	data, err := io.ReadAll(req.Body)
	assert.NoError(t, err)

	// ContentLength should match actual bytes
	assert.Equal(t, int64(len(data)), req.ContentLength)

	var got map[string]string
	err = json.Unmarshal(data, &got)
	assert.NoError(t, err)

	assert.Equal(t, "AB\nC", got["content"])
	assert.Equal(t, "XY", got["path"])
	assert.Equal(t, "EF", got["old_content"])
	assert.Equal(t, "GH\t", got["new_content"])
}

func TestSanitizeRequestBody_InvalidJSONPreservesBody(t *testing.T) {
	orig := []byte("{invalid json")
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewReader(orig))

	SanitizeRequestBody(req)

	data, err := io.ReadAll(req.Body)
	assert.NoError(t, err)
	assert.Equal(t, orig, data)
}

func TestValidationMiddleware_PostSanitizesJSON(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		var m map[string]any
		err = json.Unmarshal(data, &m)
		assert.NoError(t, err)
		// Ensure sanitization occurred
		if s, ok := m["content"].(string); ok {
			assert.Equal(t, "AB", s)
		} else {
			t.Fatalf("missing content")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(data)
	})

	mw := ValidationMiddleware(next)

	reqBody := `{"content":"A` + "\x00" + `B"}`
	req := httptest.NewRequest(http.MethodPost, "/parse", bytes.NewBufferString(reqBody))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusOK, rec.Code)
	var got map[string]string
	err := json.Unmarshal(rec.Body.Bytes(), &got)
	assert.NoError(t, err)
	assert.Equal(t, "AB", got["content"])
}

func TestValidationMiddleware_NonPostPassThrough(t *testing.T) {
	orig := `{"content":"A` + "\x00" + `B"}`
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		// For non-POST, body should be unchanged (not sanitized)
		assert.Equal(t, orig, string(data))
		w.WriteHeader(http.StatusNoContent)
	})

	mw := ValidationMiddleware(next)

	req := httptest.NewRequest(http.MethodGet, "/parse", bytes.NewBufferString(orig))
	rec := httptest.NewRecorder()

	mw.ServeHTTP(rec, req)

	assert.Equal(t, http.StatusNoContent, rec.Code)
}

func TestGetAndClearValidationErrors_Workflow(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	errs := []ValidationError{
		{Field: "a", Reason: "r1"},
		{Field: "b", Reason: "r2"},
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Equal(t, 2, len(got))
	assert.Equal(t, "a", got[0].Field)
	assert.Equal(t, "b", got[1].Field)

	// Ensure GetValidationErrors returns a copy
	got[0].Field = "mutated"
	gotAgain := GetValidationErrors()
	assert.Equal(t, "a", gotAgain[0].Field)

	ClearValidationErrors()
	gotAfterClear := GetValidationErrors()
	assert.Equal(t, 0, len(gotAfterClear))
}

func TestLogValidationErrors_Max100(t *testing.T) {
	ClearValidationErrors()
	defer ClearValidationErrors()

	var errs []ValidationError
	for i := 0; i < 120; i++ {
		errs = append(errs, ValidationError{
			Field:  "f",
			Reason: "e" + strconvIt(i),
		})
	}
	logValidationErrors(errs)

	got := GetValidationErrors()
	assert.Equal(t, 100, len(got))
	assert.Equal(t, "e20", got[0].Reason)
	assert.Equal(t, "e119", got[len(got)-1].Reason)
}

func TestContainsNullBytes(t *testing.T) {
	assert.True(t, containsNullBytes("foo\x00bar"))
	assert.False(t, containsNullBytes("foobar"))
}

// helper to avoid importing strconv for simple int->string
func strconvIt(i int) string {
	const digits = "0123456789"
	if i == 0 {
		return "0"
	}
	var b [20]byte
	pos := len(b)
	n := i
	for n > 0 {
		pos--
		b[pos] = digits[n%10]
		n /= 10
	}
	return string(b[pos:])
}
